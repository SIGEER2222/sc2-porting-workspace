#!/usr/bin/env node
// Stage 26 static gate: parse every generated/kernel Galaxy file with the
// registered sc2-galaxy-toolkit parser and record diagnostics as evidence.

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
if (!existsSync(toolkitEntry)) {
  throw new Error(`Galaxy toolkit entry missing: ${toolkitEntry}`);
}

const { Parser } = await import(pathToFileURL(toolkitEntry));

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

const kernelRoot = resolve(repoRoot, "tools/galaxy-vibe/kernel");
const files = [
  resolve(kernelRoot, "LibVibeKernel.galaxy"),
  resolve(kernelRoot, "LibVibeKernel_h.galaxy"),
  resolve(kernelRoot, "LibVibeHandles.galaxy"),
  ...(await listGalaxyFiles(resolve(kernelRoot, "generated"))),
];

const parser = new Parser();
let parseErrors = 0;
const failures = [];
let index = 0;
for (const file of files) {
  index += 1;
  const text = await readFile(file, "utf8");
  const ast = parser.parseFile(relative(kernelRoot, file).split(sep).join("/"), text);
  const diagnostics = [...(ast.diagnostics ?? []), ...(ast.parseDiagnostics ?? [])];
  if (diagnostics.length > 0) {
    parseErrors += diagnostics.length;
    failures.push({
      file: relative(repoRoot, file).split(sep).join("/"),
      errors: diagnostics.slice(0, 5).map((d) => ({
        message: d.message ?? String(d),
        line: d.range?.start?.line ?? d.line ?? null,
      })),
    });
  }
}

const evidence = {
  stage: "26-full-function-invoke",
  evidence_type: "static",
  parser: "reference/sc2-galaxy-toolkit",
  files_parsed: files.length,
  parse_errors: parseErrors,
  failures: failures.slice(0, 50),
  generated_at: new Date().toISOString(),
};
const outDir = resolve(repoRoot, "artifacts/projects/cmre-porting/stage26-full-function-invoke/static");
await mkdir(outDir, { recursive: true });
await writeFile(resolve(outDir, "parse-generated.json"), JSON.stringify(evidence, null, 2), "utf8");
console.log(JSON.stringify({ files: files.length, parseErrors, failures: failures.length }));
if (parseErrors > 0) {
  console.error(JSON.stringify(failures.slice(0, 10), null, 2));
  process.exit(1);
}
