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
let suppress = true;

for (let i = 0; i < args.length; i++) {
  const a = args[i];
  if (a === "--format") { format = args[++i]; continue; }
  if (a === "--out") { outPath = args[++i]; continue; }
  if (a === "--no-type-check") { typeCheck = false; continue; }
  if (a === "--no-suppress") { suppress = false; continue; }
  if (a === "--help" || a === "-h") {
    console.error("用法: node tools/analysis/galaxy-lint.mjs <path-or-glob> [--format json|text] [--out <file>] [--no-type-check] [--no-suppress]");
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
    const entry = [...(config.tools ?? []), ...(config.sources ?? [])].find((item) => item.id === "official-data");
    if (entry) {
      const resolvedPath = entry.path ? resolve(repoRootPath, entry.path) : local.bindings?.["official-data"];
      if (resolvedPath && existsSync(resolvedPath)) {
          const triggerLibs = join(resolvedPath, "mods", "core.sc2mod", "base.sc2data", "TriggerLibs");
          if (existsSync(triggerLibs)) {
            const dir = await opendir(triggerLibs);
            for await (const entry of dir) {
              if (entry.isFile() && extname(entry.name).toLowerCase() === ".galaxy") {
                candidates.push(join(triggerLibs, entry.name));
              }
            }
            // 引擎常量（c_targetFilter*、c_playerTypeUser 等）定义在 GameData/Game.galaxy，
            // 不在 TriggerLibs 根目录，需要单独加载，否则项目文件引用这些常量会误报 "Undeclared symbol"。
            const gameDataDir = join(triggerLibs, "GameData");
            if (existsSync(gameDataDir)) {
              const gameFile = join(gameDataDir, "Game.galaxy");
              if (existsSync(gameFile)) candidates.push(gameFile);
            }
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
function toOutputDiagnostic(d, file, source, injected = false) {
  let line = typeof d.line === "number" ? d.line + 1 : 1;
  // 注入桩 include 会在文件顶部插入一行，回拨偏移以对齐真实行号
  if (injected) line = Math.max(1, line - 1);
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
  const nativesRelSet = new Set(nativesFiles.map((f) => normalizePath(repoRootPath, f)));

  // 外部依赖声明桩：等价于 C 头文件 / TypeScript .d.ts。声明引擎常量、
  // NeuroIntegration (libEFA54406)、合作指挥官 (libCOOC) 等跨模组符号，
  // 使项目文件在脱离完整 SC2 编辑器上下文时也能解析这些引用。
  const stubPath = join(repoRootPath, "reference", "stubs", "porting-deps.galaxy");
  const stubFiles = existsSync(stubPath) ? [stubPath] : [];
  const stubRelSet = new Set(stubFiles.map((f) => normalizePath(repoRootPath, f)));
  // 同时跳过引擎 natives 与桩文件自身的诊断（它们只提供符号，不计入目标文件检查）
  const skipRelSet = new Set([...nativesRelSet, ...stubRelSet]);
  const allFiles = [...nativesFiles, ...stubFiles, ...files];
  // 记录注入了桩 include 的文件，用于在校验后回拨行号偏移
  const injectedFiles = new Set();

  for (const absFile of allFiles) {
    const relFile = normalizePath(repoRootPath, absFile);
    let text = await readFile(absFile, "utf8");
    // 为项目目标文件注入桩 include（不修改磁盘源码），使跨模组符号可解析
    const isTarget = !nativesFiles.includes(absFile) && !stubFiles.includes(absFile);
    if (isTarget) {
      text = 'include "porting-deps"\n' + text;
      injectedFiles.add(relFile);
    }
    const parser = new Parser();
    const sourceFile = parser.parseFile(relFile, text);
    documents.set(relFile, sourceFile);

    // 不收集 natives / 桩文件自身的 parser 诊断
    if (nativesFiles.includes(absFile) || stubFiles.includes(absFile)) continue;
    const parseDiags = [
      ...(sourceFile.parseDiagnostics ?? []),
      ...(sourceFile.additionalSyntacticDiagnostics ?? [])
    ];
    for (const d of parseDiags) {
      diagnostics.push(toOutputDiagnostic(d, relFile, "sc2-galaxy-lang.parser", injectedFiles.has(relFile)));
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
    // 同时 bind 桩文件：declareSymbol 依赖 bindSourceFile 预填充的 sourceFile.symbol，
    // 若桩未被 bind，checker 解析 include "porting-deps" 时会因 symbol 为 undefined 崩溃。
    const bindOrder = [...nativesFiles, ...stubFiles, ...files];
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
    // 注册项目文件的「后缀路径」key，使模组内带目录的 include（如
    // `include "scripts/cmlib/cmlib_core_h"`，其中 scripts/ 相对于 Base.SC2Data）
    // 能被 checker 解析。仅按 base 名注册时这类 include 一律报
    // "Given filename couldn't be matched"，并连锁产生大量假的 Undeclared symbol。
    // 逐级截取路径后缀注册（a/b/c、b/c、c），命中最长匹配即可。
    for (const [fileName, sourceFile] of documents) {
      const parts = fileName.toLowerCase().replace(/\.galaxy$/, "").split("/");
      for (let i = 1; i < parts.length; i++) {
        const key = parts.slice(i).join("/");
        if (!qualifiedDocuments.has(key)) qualifiedDocuments.set(key, new Map());
        if (!qualifiedDocuments.get(key).has(fileName)) qualifiedDocuments.get(key).set(fileName, sourceFile);
      }
    }
    // 注册 `triggerlibs/<base>` 形式的 key，使 `include "TriggerLibs/natives"` 这类带目录的
    // include 语句能被 checker 解析（checker 用完整 include 路径作为 qualifiedDocuments 的 key）。
    for (const absFile of nativesFiles) {
      const base = absFile.split(/[\\/]/).pop().toLowerCase().replace(/\.galaxy$/, "");
      const tlKey = "triggerlibs/" + base;
      const relFile = normalizePath(repoRootPath, absFile);
      const sf = documents.get(relFile);
      if (sf) {
        if (!qualifiedDocuments.has(tlKey)) qualifiedDocuments.set(tlKey, new Map());
        qualifiedDocuments.get(tlKey).set(relFile, sf);
      }
    }
    // 注册外部依赖桩文件：让项目文件已有的 include "LibEFA54406_h" 等语句解析到桩，
    // 从而解析 NeuroIntegration / 合作指挥官 / 引擎常量 / 兄弟库发布函数等跨模组符号。
    // （checker 按 fileName 去重，porting-deps 与 libefa54406_h 指向同一文件不会重复加载）
    for (const absFile of stubFiles) {
      const relFile = normalizePath(repoRootPath, absFile);
      const sf = documents.get(relFile);
      if (!sf) continue;
      for (const key of ["libefa54406_h", "libefa54406", "porting-deps", "libcooc", "libportingobserver"]) {
        if (!qualifiedDocuments.has(key)) qualifiedDocuments.set(key, new Map());
        if (!qualifiedDocuments.get(key).has(relFile)) qualifiedDocuments.get(key).set(relFile, sf);
      }
    }

    // 构造 s2workspace，让 checkSourceFileRecursively 自动加载 natives
    // checkSourceFileRecursively 用 URI.file(fpath).toString() 作为 key 查 documents
    // 因此需要把 natives 文件也以 URI 格式 key 存入 documents
    let s2workspace = null;
    // 注意：故意不设置 s2workspace。若设置 core.sc2mod archive，sc2-galaxy-lang 的 checker
    // 会自行加载并递归类型检查整个引擎 TriggerLibs，而引擎库之间在脱离完整 SC2 编辑器
    // 上下文时 include 依赖无法完全解析，会产生数千条误报。这里改为完全依赖
    // qualifiedDocuments（已为 natives 注册 triggerlibs/<base> 形式的 key）解析 include，
    // checker 只递归检查项目文件真正 include 的引擎文件。
    if (false && nativesFiles.length > 0) {
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
      if (skipRelSet.has(fileName)) continue;
      try {
        const result = checker.checkSourceFileRecursively(sourceFile);
        const checkerDiags = result.diagnostics;
        if (checkerDiags instanceof Map) {
          for (const [diagFile, diags] of checkerDiags) {
            // checkSourceFileRecursively 会递归进入项目文件 include 的引擎文件 / 桩文件，
            // 这些在脱离 SC2 编辑器上下文时会报出大量 "Undeclared symbol" 误报。
            // 按相对路径过滤掉引擎 native 与桩文件的诊断（仅报告真正的目标文件问题）。
            if (skipRelSet.has(diagFile) || skipRelSet.has(diagFile.split(/[\\/]/).join("/"))) continue;
            for (const d of diags) {
              // 桩文件为提供跨文件函数体（如 libPortingObserver_gf_Publish）会与其在
              // 项目文件中的真实定义产生 "Symbol redeclared" 提示；这是桩机制的有意产物，
              // 真实定义才是权威实现，因此抑制指向桩文件的重声明诊断。
              const diagMsg = (d.messageText || d.message || "");
              if (stubRelSet.size > 0 && /porting-deps\.galaxy/.test(diagMsg)) continue;
              diagnostics.push(toOutputDiagnostic(d, diagFile, "sc2-galaxy-lang.checker", injectedFiles.has(diagFile)));
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

// ---------- 已知良性诊断抑制（R3 专项） ----------
// 规则来自同目录 galaxy-lint-suppressions.json。仅抑制 error 严重度；
// warning / suggestion 保留可见，以不丢失任何非门禁信号。
function buildMatcher(rule) {
  switch (rule.match) {
    case "messageStartsWith": return (m) => m.startsWith(rule.pattern);
    case "messageContains":   return (m) => m.includes(rule.pattern);
    case "messageRegex":      return (m) => new RegExp(rule.pattern).test(m);
    default:                  return null;
  }
}

async function loadSuppressions(scriptDirPath) {
  const path = join(scriptDirPath, "galaxy-lint-suppressions.json");
  if (!existsSync(path)) return [];
  try {
    const cfg = JSON.parse(await readFile(path, "utf8"));
    return (cfg.rules || []).filter((r) => r && r.id && r.pattern && buildMatcher(r));
  } catch (e) {
    if (process.env.GALAXY_LINT_DEBUG) console.error("加载抑制规则失败: " + e.message);
    return [];
  }
}

function applySuppressions(diagnostics, rules, enabled) {
  if (!enabled || rules.length === 0) {
    return { filtered: diagnostics, suppressedByRule: {}, suppressed: 0 };
  }
  const matchers = rules.map((r) => ({ id: r.id, fn: buildMatcher(r) }));
  const suppressedByRule = {};
  const filtered = [];
  for (const d of diagnostics) {
    if (d.severity !== "error") { filtered.push(d); continue; }
    const msg = d.message || "";
    let matched = false;
    for (const m of matchers) {
      if (m.fn(msg)) { suppressedByRule[m.id] = (suppressedByRule[m.id] || 0) + 1; matched = true; break; }
    }
    if (!matched) filtered.push(d);
  }
  const suppressed = diagnostics.length - filtered.length;
  return { filtered, suppressedByRule, suppressed };
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

  // R3：抑制已知良性诊断（隔离 lint 下的全局命名空间 / checker 限制误报）
  const suppressions = await loadSuppressions(scriptDir);
  const { filtered, suppressedByRule, suppressed } = applySuppressions(diagnostics, suppressions, suppress);
  if (suppressed > 0) {
    console.error(`[galaxy-lint] 抑制已知良性诊断 ${suppressed} 条（--no-suppress 可关闭以核对）:`);
    for (const [id, n] of Object.entries(suppressedByRule).sort((a, b) => b[1] - a[1])) {
      console.error(`  - ${id}: ${n}`);
    }
  }
  const result = buildOutput(filtered, files.length, analyzerVersion);

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
