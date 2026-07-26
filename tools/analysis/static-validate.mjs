import { mkdir, opendir, readFile, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(scriptDir, "..", "..");

async function readJson(path) {
  return JSON.parse(await readFile(path, "utf8"));
}

function runTool(cmd, args, options = {}) {
  return new Promise((resolvePromise, rejectPromise) => {
    const child = spawn(cmd, args, { stdio: "inherit", shell: false, ...options });
    child.on("error", rejectPromise);
    child.on("close", (code) => {
      if (code === 0 || code === 1) resolvePromise(code);
      else rejectPromise(new Error(`${cmd} exited with code ${code}`));
    });
  });
}

async function validateProject(projectId, stageDir, outDir) {
  const projectDir = join(repoRoot, "src", "projects", projectId);
  const compositionPath = join(projectDir, "manifests", "composition.json");

  if (!existsSync(compositionPath)) {
    throw new Error("Composition manifest not found: " + compositionPath);
  }

  const absOut = resolve(repoRoot, outDir || join(stageDir || projectDir, "evidence", "static"));
  await mkdir(absOut, { recursive: true });

  const commands = [];
  let overallPass = true;

  // 1. galaxy-lint
  commands.push({ name: "galaxy-lint", file: "diagnostics.json" });
  const lintCode = await runTool("node", [
    join(scriptDir, "galaxy-lint.mjs"),
    projectDir,
    "--format", "json",
    "--out", join(absOut, "diagnostics.json")
  ]);
  if (lintCode === 1) overallPass = false;

  // 2. analyze-galaxy
  commands.push({ name: "analyze-galaxy", file: "galaxy-graph.json" });
  await runTool("node", [
    join(scriptDir, "analyze-galaxy.mjs"),
    "--composition", compositionPath,
    join(absOut, "galaxy-graph.json")
  ]);

  // 3. analyze-catalog (针对 composition 中的所有 package)
  commands.push({ name: "analyze-catalog", file: "catalog-graph.json" });
  const manifest = await readJson(compositionPath);
  if (manifest.packages && manifest.packages.length > 0) {
    const firstPkg = manifest.packages[0];
    await runTool("node", [
      join(scriptDir, "analyze-catalog.mjs"),
      firstPkg.sourceId,
      firstPkg.path || ".",
      ".*",
      join(absOut, "catalog-graph.json")
    ]);
  }

  // 4. 合并依赖图
  commands.push({ name: "merge-dependency-graph", file: "dependency-graph.json" });
  const mergedGraph = await mergeDependencyGraphs(absOut);
  await writeFile(join(absOut, "dependency-graph.json"), JSON.stringify(mergedGraph, null, 2) + "\n", "utf8");

  // 5. validate-packaging
  commands.push({ name: "validate-packaging", file: "packaging-report.json" });
  const pkgCode = await runTool("node", [
    join(scriptDir, "validate-packaging.mjs"),
    compositionPath,
    join(absOut, "packaging-report.json"),
    join(absOut, "dependency-graph.json")
  ]);
  if (pkgCode === 1) overallPass = false;

  // 6. validate-schema
  commands.push({ name: "validate-schema", file: "schema-validation.json" });
  const schemaCode = await runTool("node", [
    join(scriptDir, "validate-schema.mjs"),
    join(absOut, "diagnostics.json"), "docs/schemas/static-diagnostics.schema.json",
    join(absOut, "dependency-graph.json"), "docs/schemas/dependency-graph.schema.json",
    join(absOut, "packaging-report.json"), "docs/schemas/packaging-report.schema.json"
  ]);
  if (schemaCode === 1) overallPass = false;

  // 7. 写入 analyzer-commands
  await writeFile(join(absOut, "analyzer-commands.json"), JSON.stringify(commands, null, 2) + "\n", "utf8");

  // 8. 写入 unresolved.json
  const unresolved = mergedGraph.unresolved || [];
  await writeFile(join(absOut, "unresolved.json"), JSON.stringify(unresolved, null, 2) + "\n", "utf8");

  // 9. 写入 stage-verdict.json
  const verdict = {
    schemaVersion: 1,
    generatedAt: new Date().toISOString(),
    compositionId: manifest.compositionId,
    stage: "static-validation",
    status: overallPass ? "pass" : "fail",
    checks: commands.map((c) => ({
      name: c.name,
      file: c.file,
      status: overallPass ? "pass" : "fail"
    }))
  };
  await writeFile(join(absOut, "stage-verdict.json"), JSON.stringify(verdict, null, 2) + "\n", "utf8");

  console.log(`\n=== Static Validation ${overallPass ? "PASSED" : "FAILED"} ===`);
  process.exitCode = overallPass ? 0 : 1;
}

async function mergeDependencyGraphs(outDir) {
  const galaxyPath = join(outDir, "galaxy-graph.json");
  const catalogPath = join(outDir, "catalog-graph.json");

  const merged = {
    schemaVersion: 1,
    composition: "merged",
    nodes: [],
    edges: [],
    unresolved: []
  };

  if (existsSync(galaxyPath)) {
    const galaxy = await readJson(galaxyPath);
    merged.nodes.push(...galaxy.nodes || []);
    merged.edges.push(...galaxy.edges || []);
    merged.unresolved.push(...galaxy.unresolved || []);
    merged.composition = galaxy.composition || "merged";
  }

  if (existsSync(catalogPath)) {
    const catalog = await readJson(catalogPath);
    merged.nodes.push(...catalog.nodes || []);
    merged.edges.push(...catalog.edges || []);
    merged.unresolved.push(...catalog.unresolved || []);
  }

  return merged;
}

async function main() {
  const args = process.argv.slice(2);

  if (args[0] === "--request") {
    const requestPath = args[1];
    const outDir = args[3];
    if (!requestPath || !outDir) {
      throw new Error("Usage: node tools/analysis/static-validate.mjs --request <static-analysis-request.json> --out-dir <dir>");
    }
    const request = await readJson(resolve(repoRoot, requestPath));
    await validateProject(request.compositionId, null, outDir);
  } else {
    const projectId = args[0];
    const stageDir = args[1];
    if (!projectId) {
      throw new Error("Usage: node tools/analysis/static-validate.mjs <project-id> [--stage <stage-dir>]");
    }
    await validateProject(projectId, stageDir, null);
  }
}

main().catch((e) => {
  console.error("static-validate failed: " + e.message);
  process.exitCode = 2;
});