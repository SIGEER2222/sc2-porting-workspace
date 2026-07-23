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

// 查找 SC2GameData 的 natives.galaxy 和 natives_missing.galaxy
// 这两个文件声明了所有引擎内置 native 函数，加载后可避免误报 "Undeclared symbol"
async function findNativesFiles(repoRootPath) {
  const candidates = [];
  try {
    const config = await readJson(join(repoRootPath, "src", "config", "workspace.json"));
    const localPath = join(repoRootPath, "src", "config", "local.sources.json");
    const local = existsSync(localPath) ? await readJson(localPath) : { bindings: {} };
    // SC2GameData 在 workspace.json 注册为 "official-data"
    const entry = [...(config.tools ?? []), ...(config.sources ?? [])].find((item) => item.id === "official-data");
    if (entry) {
      const resolvedPath = entry.path ? resolve(repoRootPath, entry.path) : local.bindings?.["official-data"];
      if (resolvedPath && existsSync(resolvedPath)) {
        const triggerLibs = join(resolvedPath, "mods", "core.sc2mod", "base.sc2data", "TriggerLibs");
        for (const name of ["natives.galaxy", "natives_missing.galaxy"]) {
          const file = join(triggerLibs, name);
          if (existsSync(file)) candidates.push(file);
        }
      }
    }
  } catch { /* 忽略配置读取失败，返回空列表 */ }
  return candidates;
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
// DiagnosticCategory: Error=1, Warning=2, Message=3, Hint=4
function toOutputDiagnostic(d, file, source) {
  const line = typeof d.line === "number" ? d.line + 1 : 1;
  const column = typeof d.col === "number" ? d.col + 1 : 1;
  const severity = d.category === 1 ? "error" :
                   d.category === 2 ? "warning" :
                   d.category === 3 ? "info" :
                   d.category === 4 ? "suggestion" : "info";
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

  // 1. parse 阶段：先加载 SC2 引擎 native 函数声明，再 parse 目标文件
  // natives.galaxy 声明了所有引擎内置函数（AICreateOrder、UnitOrder 等），
  // 加载后可避免 native 函数被误报为 "Undeclared symbol"
  const nativesFiles = await findNativesFiles(repoRootPath);
  const allFiles = [...nativesFiles, ...files];

  for (const absFile of allFiles) {
    const relFile = normalizePath(repoRootPath, absFile);
    const text = await readFile(absFile, "utf8");
    const parser = new Parser();
    const sourceFile = parser.parseFile(relFile, text);
    documents.set(relFile, sourceFile);

    // 只收集目标文件的 parser 诊断，不收集 natives 文件的诊断
    if (nativesFiles.includes(absFile)) continue;
    const parseDiags = [
      ...(sourceFile.parseDiagnostics ?? []),
      ...(sourceFile.additionalSyntacticDiagnostics ?? [])
    ];
    for (const d of parseDiags) {
      diagnostics.push(toOutputDiagnostic(d, relFile, "sc2-galaxy-lang.parser"));
    }
  }

  // 2. bind 阶段：用共享 store 为所有文件建立符号表
  // store 提供 resolveGlobalSymbol，让跨文件符号解析生效
  // 必须先 bind natives.galaxy，让 native 函数进入 globalSymbols
  if (typeCheck) {
    const globalSymbols = new Map();
    const store = {
      resolveGlobalSymbol: (name) => globalSymbols.get(name) ?? null
    };
    // 先 bind natives 文件，让 native 函数先进入 globalSymbols
    const bindOrder = [...nativesFiles, ...files];
    for (const absFile of bindOrder) {
      const relFile = normalizePath(repoRootPath, absFile);
      const sourceFile = documents.get(relFile);
      if (!sourceFile) continue;
      try {
        bindSourceFile(sourceFile, store);
        // 收集全局符号到 globalSymbols，供后续文件解析
        if (sourceFile.symbol?.members) {
          for (const [name, sym] of sourceFile.symbol.members) {
            if (!globalSymbols.has(name)) {
              globalSymbols.set(name, sym);
            }
          }
        }
      } catch (e) {
        // 只对目标文件报告 bind 失败，natives 文件失败静默
        if (nativesFiles.includes(absFile)) continue;
        diagnostics.push({
          file: relFile,
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
    // 构建 qualifiedDocuments：按去后缀小写文件名索引，供 checker 解析 include
    // checkIncludeStatement 用 path.toLowerCase().replace(/\.galaxy$/, '') 查找
    const qualifiedDocuments = new Map();
    for (const [fileName, sourceFile] of documents) {
      const base = fileName.split("/").pop().toLowerCase().replace(/\.galaxy$/, "");
      if (!qualifiedDocuments.has(base)) {
        qualifiedDocuments.set(base, new Map());
      }
      qualifiedDocuments.get(base).set(fileName, sourceFile);
    }

    // 构造 s2workspace，让 checkSourceFileRecursively 自动加载 natives
    // checkSourceFileRecursively 用 URI.file(fpath).toString() 作为 key 查 documents
    // 因此需要把 natives 文件也以 URI 格式 key 存入 documents
    let s2workspace = null;
    if (nativesFiles.length > 0) {
      const config = await readJson(join(repoRootPath, "src", "config", "workspace.json"));
      const officialEntry = [...(config.tools ?? []), ...(config.sources ?? [])]
        .find((item) => item.id === "official-data");
      if (officialEntry) {
        const officialRoot = resolve(repoRootPath, officialEntry.path);
        const coreDir = join(officialRoot, "mods", "core.sc2mod");
        s2workspace = {
          allArchives: [
            { name: "mods/core.sc2mod", directory: coreDir }
          ]
        };
        // 补充 URI 格式的 key，让 checker 能查到 natives 文件
        for (const absFile of nativesFiles) {
          const relFile = normalizePath(repoRootPath, absFile);
          const sourceFile = documents.get(relFile);
          if (sourceFile) {
            // URI.file 需要正斜杠路径
            const uriKey = "file:///" + absFile.replace(/\\/g, "/").replace(/^\//, "");
            documents.set(uriKey, sourceFile);
          }
        }
      }
    }

    const host = { documents, qualifiedDocuments, s2workspace };
    const checker = new TypeChecker(host);
    for (const [fileName, sourceFile] of documents) {
      const absFile = join(repoRootPath, fileName.split("/").join(sep));
      if (nativesFiles.includes(absFile)) continue;
      try {
        const result = checker.checkSourceFileRecursively(sourceFile);
        const checkerDiags = result.diagnostics;
        if (checkerDiags instanceof Map) {
          for (const [diagFile, diags] of checkerDiags) {
            for (const d of diags) {
              diagnostics.push(toOutputDiagnostic(d, diagFile, "sc2-galaxy-lang.checker"));
            }
          }
        }
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
