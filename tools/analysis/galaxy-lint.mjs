// Galaxy 脚本静态诊断工具：调用 sc2-galaxy-lang 的 parser/binder/checker
// 输出 syntax + type 诊断到 stdout 或文件，与 analyze-galaxy.mjs 的 dependency graph 互补
// 用法：node tools/analysis/galaxy-lint.mjs <path-or-glob> [--format json|text] [--out <file>] [--no-type-check]

import { mkdir, opendir, readFile, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, extname, join, relative, resolve, sep } from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(scriptDir, "..", "..");

// CLI 参数解析
const args = process.argv.slice(2);
let targetPath = null;
let format = "json";
let outPath = null;
let typeCheck = true;

for (let i = 0; i < args.length; i++) {
  const a = args[i];
  if (a === "--format") { format = args[++i]; continue; }
  if (a === "--out") { outPath = args[++i]; continue; }
  if (a === "--no-type-check") { typeCheck = false; continue; }
  if (a === "--help" || a === "-h") {
    console.error("用法: node tools/analysis/galaxy-lint.mjs <path-or-glob> [--format json|text] [--out <file>] [--no-type-check]");
    process.exit(0);
  }
  if (!a.startsWith("--")) targetPath = a;
}

if (!targetPath) {
  console.error("错误：缺少目标路径。使用 --help 查看用法");
  process.exit(1);
}

// ---------- 工具函数（复用 analyze-galaxy.mjs 模式） ----------

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

async function loadToolkit() {
  const toolkitRoot = await resolveRegistered("galaxy-toolkit");
  const galaxyModule = join(toolkitRoot, "packages", "sc2-galaxy-lang", "lib", "src", "index.js");
  if (!existsSync(galaxyModule)) {
    throw new Error(
      `sc2-galaxy-lang 未构建：${galaxyModule} 不存在\n` +
      `请先在 reference/sc2-galaxy-toolkit/ 下执行：\n` +
      `  pnpm install\n  pnpm -r run build`
    );
  }
  return await import(pathToFileURL(galaxyModule));
}

async function listGalaxyFiles(target) {
  const abs = resolve(target);
  if (!existsSync(abs)) {
    throw new Error("路径不存在: " + abs);
  }
  const stat = await import("node:fs/promises").then(m => m.stat);
  const isDir = (await import("node:fs/promises").then(m => m.stat))(abs);
  if (!(await isDir).isDirectory()) {
    return [abs];
  }
  const files = [];
  async function walk(path) {
    const directory = await opendir(path);
    for await (const entry of directory) {
      const child = join(path, entry.name);
      if (entry.isDirectory()) await walk(child);
      else if (entry.isFile() && extname(entry.name).toLowerCase() === ".galaxy") files.push(child);
    }
  }
  await walk(abs);
  return files.sort((left, right) => left.localeCompare(right));
}

// ---------- 主诊断逻辑 ----------

function normalizePath(root, path) {
  return relative(root, path).split(sep).join("/");
}

// 将 sc2-galaxy-lang 的 Diagnostic 转为统一输出格式
function toOutputDiagnostic(d, file, source) {
  const line = typeof d.line === "number" ? d.line + 1 : (d.start != null && d.file ? 1 : 1);
  const column = typeof d.col === "number" ? d.col + 1 : 1;
  const severity = d.category === 0 ? "error" :
                   d.category === 1 ? "warning" :
                   d.category === 2 ? "suggestion" : "info";
  return {
    file,
    line,
    column,
    severity,
    code: d.code != null ? `G${String(d.code).padStart(3, "0")}` : "G000",
    message: d.messageText || d.message || "",
    source
  };
}

async function lintFiles(files, repoRootPath) {
  const { Parser, bindSourceFile, TypeChecker } = await loadToolkit();

  const diagnostics = [];
  const documents = new Map();
  const parseDiagnosticsByFile = new Map();

  // 1. parse 阶段：所有文件先 parse，建立 documents map
  for (const absFile of files) {
    const relFile = normalizePath(repoRootPath, absFile);
    const text = await readFile(absFile, "utf8");
    const parser = new Parser();
    const sourceFile = parser.parseFile(relFile, text);
    documents.set(relFile, sourceFile);

    // 收集 parser 产生的语法诊断
    const parseDiags = [
      ...(sourceFile.parseDiagnostics ?? []),
      ...(sourceFile.additionalSyntacticDiagnostics ?? [])
    ];
    for (const d of parseDiags) {
      diagnostics.push(toOutputDiagnostic(d, relFile, "sc2-galaxy-lang.parser"));
    }
  }

  // 2. bind 阶段：为每个文件建立符号表
  if (typeCheck) {
    for (const [fileName, sourceFile] of documents) {
      try {
        bindSourceFile(sourceFile);
      } catch (e) {
        // bind 失败不致命，记录后继续
        diagnostics.push({
          file: fileName,
          line: 1,
          column: 1,
          severity: "warning",
          code: "G900",
          message: `binder 失败: ${e.message}`,
          source: "galaxy-lint.binder"
        });
      }
    }

    // 3. type check 阶段
    // TypeChecker 需要 host 提供 documents Map
    const host = { documents };
    const checker = new TypeChecker(host);
    for (const [fileName, sourceFile] of documents) {
      try {
        checker.checkSourceFile(sourceFile, false);
      } catch (e) {
        diagnostics.push({
          file: fileName,
          line: 1,
          column: 1,
          severity: "warning",
          code: "G901",
          message: `checker 失败: ${e.message}`,
          source: "galaxy-lint.checker"
        });
      }
    }

    // 从 checker 私有 diagnostics map 收集（编译后字段可访问）
    const checkerDiags = checker.diagnostics;
    if (checkerDiags instanceof Map) {
      for (const [fileName, diags] of checkerDiags) {
        for (const d of diags) {
          diagnostics.push(toOutputDiagnostic(d, fileName, "sc2-galaxy-lang.checker"));
        }
      }
    }
  }

  // 排序：按文件名 → 行号 → 列号
  diagnostics.sort((a, b) =>
    a.file.localeCompare(b.file) ||
    a.line - b.line ||
    a.column - b.column
  );

  return diagnostics;
}

function buildOutput(diagnostics, filesCount, analyzerVersion) {
  const errors = diagnostics.filter(d => d.severity === "error").length;
  const warnings = diagnostics.filter(d => d.severity === "warning").length;
  const suggestions = diagnostics.filter(d => d.severity === "suggestion").length;

  return {
    schemaVersion: 1,
    generatedAt: new Date().toISOString(),
    tool: "galaxy-lint@0.1.0",
    analyzer: `sc2-galaxy-lang@${analyzerVersion}`,
    files: filesCount,
    diagnostics,
    summary: {
      errors,
      warnings,
      suggestions,
      total: diagnostics.length
    }
  };
}

function formatAsText(result) {
  const lines = [];
  lines.push(`galaxy-lint 诊断报告`);
  lines.push(`生成时间: ${result.generatedAt}`);
  lines.push(`分析器: ${result.analyzer}`);
  lines.push(`文件数: ${result.files}`);
  lines.push(`---`);
  for (const d of result.diagnostics) {
    const sev = d.severity.toUpperCase().padEnd(5);
    lines.push(`${d.file}:${d.line}:${d.column}  ${sev} ${d.code}  ${d.message}  [${d.source}]`);
  }
  lines.push(`---`);
  lines.push(`合计: ${result.summary.total} 条 (${result.summary.errors} 错误, ${result.summary.warnings} 警告, ${result.summary.suggestions} 建议)`);
  return lines.join("\n");
}

// ---------- 入口 ----------

try {
  const files = await listGalaxyFiles(targetPath);
  if (files.length === 0) {
    console.error("未找到 .galaxy 文件: " + targetPath);
    process.exit(1);
  }

  let analyzerVersion = "unknown";
  try {
    const toolkitRoot = await resolveRegistered("galaxy-toolkit");
    const pkgJson = JSON.parse(await readFile(join(toolkitRoot, "packages", "sc2-galaxy-lang", "package.json"), "utf8"));
    analyzerVersion = pkgJson.version ?? "unknown";
  } catch { /* 忽略版本读取失败 */ }

  const diagnostics = await lintFiles(files, repoRoot);
  const result = buildOutput(diagnostics, files.length, analyzerVersion);

  if (outPath) {
    const absOut = resolve(outPath);
    await mkdir(dirname(absOut), { recursive: true });
    const content = format === "text" ? formatAsText(result) : JSON.stringify(result, null, 2) + "\n";
    await writeFile(absOut, content, "utf8");
    console.error(`诊断结果已写入: ${absOut}`);
  } else {
    if (format === "text") {
      console.log(formatAsText(result));
    } else {
      console.log(JSON.stringify(result, null, 2));
    }
  }

  // 退出码：有 error 则 1，否则 0
  process.exitCode = result.summary.errors > 0 ? 1 : 0;
} catch (e) {
  console.error("galaxy-lint 失败: " + e.message);
  if (e.stack && process.env.GALAXY_LINT_DEBUG) {
    console.error(e.stack);
  }
  process.exitCode = 2;
}
