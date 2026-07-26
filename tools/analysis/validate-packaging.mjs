import { mkdir, opendir, readFile, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, extname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";

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

async function runMpqVerify(mpqPath) {
  const mpqScript = join(repoRoot, "tools", "mpq", "scripts", "verify_mpq.py");
  if (!existsSync(mpqScript)) {
    return { valid: null, error: "verify_mpq.py not found" };
  }
  return new Promise((resolve) => {
    const child = spawn("python", [mpqScript, mpqPath]);
    let stderr = "";
    child.stderr.on("data", (data) => { stderr += data.toString(); });
    child.on("close", (code) => {
      resolve({ valid: code === 0, error: code !== 0 ? stderr.trim() : null });
    });
    child.on("error", (err) => {
      resolve({ valid: null, error: err.message });
    });
  });
}

async function validate(compositionPath, dependencyGraphPath, outputPath) {
  const manifest = await readJson(resolve(repoRoot, compositionPath));
  const checks = [];
  const packages = [];

  // 1. composition 包完整性校验
  const compCheck = { id: "composition-integrity", name: "Composition Package Integrity", status: "pass", findings: [] };
  for (const pkg of manifest.packages) {
    const pkgInfo = { packageId: pkg.packageId ?? pkg.sourceId, sourceId: pkg.sourceId, path: pkg.path, exists: false };
    try {
      const sourceRoot = await resolveRegistered(pkg.sourceId);
      const pkgRoot = resolve(sourceRoot, pkg.path ?? ".");
      pkgInfo.path = pkgRoot;
      pkgInfo.exists = existsSync(pkgRoot);
      if (!pkgInfo.exists) {
        compCheck.findings.push({ level: "error", message: `Package not found: ${pkg.sourceId}/${pkg.path}`, path: pkgRoot });
        compCheck.status = "fail";
      }
    } catch (e) {
      compCheck.findings.push({ level: "error", message: `Failed to resolve package: ${e.message}`, path: pkg.path });
      compCheck.status = "fail";
    }
    packages.push(pkgInfo);
  }
  checks.push(compCheck);

  // 2. 文档声明文件校验
  const declCheck = { id: "document-declarations", name: "Document Declaration Files", status: "pass", findings: [] };
  const requiredDeclarations = [
    "DocumentInfo", "DocumentHeader", "ComponentList.SC2Components",
    "GameData.version", "GameText.version", "Triggers.version", "Preload.xml"
  ];

  for (const pkgInfo of packages) {
    if (!pkgInfo.exists) continue;
    pkgInfo.declarations = [];
    const isMpq = [".sc2map", ".sc2mod"].includes(extname(pkgInfo.path).toLowerCase());
    pkgInfo.isMpq = isMpq;

    if (!isMpq) {
      for (const decl of requiredDeclarations) {
        const declPath = join(pkgInfo.path, decl);
        const exists = existsSync(declPath);
        pkgInfo.declarations.push({ name: decl, exists, path: declPath });
        if (!exists) {
          declCheck.findings.push({ level: "warning", message: `Missing declaration: ${decl}`, path: declPath });
          declCheck.status = "warning";
        }
      }
    }
  }
  checks.push(declCheck);

  // 3. MPQ 结构校验
  const mpqCheck = { id: "mpq-structure", name: "MPQ Package Structure", status: "pass", findings: [] };
  for (const pkgInfo of packages) {
    if (!pkgInfo.exists || !pkgInfo.isMpq) {
      pkgInfo.mpqValid = false;
      continue;
    }
    const result = await runMpqVerify(pkgInfo.path);
    pkgInfo.mpqValid = result.valid === true;
    if (result.valid === false) {
      mpqCheck.findings.push({ level: "error", message: `MPQ validation failed: ${result.error}`, path: pkgInfo.path });
      mpqCheck.status = "fail";
    } else if (result.valid === null) {
      mpqCheck.findings.push({ level: "warning", message: `MPQ validation skipped: ${result.error}`, path: pkgInfo.path });
      mpqCheck.status = "warning";
    }
  }
  checks.push(mpqCheck);

  // 4. 未解析依赖校验（如果提供了 dependency-graph）
  if (dependencyGraphPath && existsSync(resolve(repoRoot, dependencyGraphPath))) {
    const graph = await readJson(resolve(repoRoot, dependencyGraphPath));
    const depCheck = { id: "unresolved-dependencies", name: "Unresolved Dependencies", status: "pass", findings: [] };
    if (graph.unresolved && graph.unresolved.length > 0) {
      depCheck.status = "warning";
      for (const item of graph.unresolved) {
        depCheck.findings.push({ level: "warning", message: item.description, path: "" });
      }
    }
    checks.push(depCheck);
  }

  // 汇总统计
  const summary = {
    total: checks.length,
    passed: checks.filter((c) => c.status === "pass").length,
    failed: checks.filter((c) => c.status === "fail").length,
    warnings: checks.filter((c) => c.status === "warning").length
  };

  const result = {
    schemaVersion: 1,
    generatedAt: new Date().toISOString(),
    compositionId: manifest.compositionId ?? "unnamed",
    summary,
    checks,
    packages
  };

  const absOut = resolve(repoRoot, outputPath);
  await mkdir(dirname(absOut), { recursive: true });
  await writeFile(absOut, JSON.stringify(result, null, 2) + "\n", "utf8");
  console.log(JSON.stringify(summary, null, 2));

  process.exitCode = summary.failed > 0 ? 1 : 0;
}

const args = process.argv.slice(2);
if (args.length < 2 || args.length > 3) {
  throw new Error("Usage: node tools/analysis/validate-packaging.mjs <composition.json> <output-path> [dependency-graph.json]");
}
await validate(args[0], args[2], args[1]);