# 完善静态校验部分实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完善 SC2 移植工作流的静态校验部分，包括修复路径 bug、对齐 dependency-graph schema、新增编排器、packaging 校验和 schema 校验。

**Architecture:** 方案 C — 直接改造 `analyze-galaxy.mjs` 和 `analyze-catalog.mjs` 输出符合 `dependency-graph.schema.json` 的 `{nodes, edges, unresolved}` 结构；新增 `static-validate.mjs` 作为统一编排入口；`workspace.mjs` 薄转发；保留向后兼容。

**Tech Stack:** Node.js (ES Modules), sc2-galaxy-toolkit (Parser/Binder/TypeChecker), sc2-data (DeepCatalogStore), Python (verify_mpq.py)

---

## 文件结构

### 修改文件
| 文件 | 职责 | 修改内容 |
|------|------|----------|
| `tools/analysis/analyze-galaxy.mjs` | Galaxy 依赖分析 | 路径修复 + 输出对齐 dependency-graph schema |
| `tools/analysis/analyze-catalog.mjs` | Catalog 依赖分析 | 路径修复 + 输出对齐 dependency-graph schema |
| `tools/analysis/extract-catalog-boundary.mjs` | Catalog 边界抽取 | 路径修复 |
| `tools/analysis/compare-catalog-chains.mjs` | Catalog 链对比 | 路径修复 |
| `tools/analysis/galaxy-lint.mjs` | Galaxy 语法/类型诊断 | 跨 mod 头文件注入改进 |
| `tools/utils/workspace.mjs` | 工作区管理入口 | 新增 `static-validate` 子命令 |
| `docs/workflow.md` | 工作流文档 | 更新 stage 6 说明 |
| `tools/.codex/skills/sc2-static-analysis/SKILL.md` | 静态分析技能定义 | 更新用法说明 |
| `tools/.codex/skills/sc2-static-analysis/references/output-contract.md` | 输出契约 | 更新输出格式 |
| `tools/README.md` | 工具目录规范 | 更新工具清单 |

### 新增文件
| 文件 | 职责 |
|------|------|
| `tools/analysis/static-validate.mjs` | 静态校验编排器 |
| `tools/analysis/validate-packaging.mjs` | packaging 校验器 |
| `tools/analysis/validate-schema.mjs` | schema 校验器 |
| `docs/schemas/packaging-report.schema.json` | packaging report 格式定义 |

---

## Task 1: 修复分析器配置路径（4 个文件）

**Files:**
- Modify: `tools/analysis/analyze-galaxy.mjs:19-21`
- Modify: `tools/analysis/analyze-catalog.mjs:14-16`
- Modify: `tools/analysis/extract-catalog-boundary.mjs:15-16`
- Modify: `tools/analysis/compare-catalog-chains.mjs:14-15`

- [ ] **Step 1: 修改 analyze-galaxy.mjs 的配置路径**

```javascript
async function resolveRegistered(id) {
  const config = await readJson(join(repoRoot, "src", "config", "workspace.json"));
  const localPath = join(repoRoot, "src", "config", "local.sources.json");
  const local = existsSync(localPath) ? await readJson(localPath) : { bindings: {} };
  // ... rest unchanged
}
```

- [ ] **Step 2: 修改 analyze-catalog.mjs 的配置路径**

```javascript
async function resolveRegistered(id) {
  const config = await readJson(join(repoRoot, "src", "config", "workspace.json"));
  const localPath = join(repoRoot, "src", "config", "local.sources.json");
  const local = existsSync(localPath) ? await readJson(localPath) : { bindings: {} };
  // ... rest unchanged
}
```

- [ ] **Step 3: 修改 extract-catalog-boundary.mjs 的配置路径**

```javascript
async function resolveRegistered(id) {
  const config = await readJson(join(repoRoot, "src", "config", "workspace.json"));
  const localPath = join(repoRoot, "src", "config", "local.sources.json");
  const local = existsSync(localPath) ? await readJson(localPath) : { bindings: {} };
  // ... rest unchanged
}
```

- [ ] **Step 4: 修改 compare-catalog-chains.mjs 的配置路径**

```javascript
async function resolveRegistered(id) {
  const config = await readJson(join(repoRoot, "src", "config", "workspace.json"));
  const localPath = join(repoRoot, "src", "config", "local.sources.json");
  const local = existsSync(localPath) ? await readJson(localPath) : { bindings: {} };
  // ... rest unchanged
}
```

- [ ] **Step 5: 修正 analyze-galaxy.mjs 的 usage 字符串**

```javascript
// 第 319 行：
throw new Error("Usage: node tools/analysis/analyze-galaxy.mjs --composition <manifest.json> <output-path>");
// 第 325 行：
throw new Error("Usage: node tools/analysis/analyze-galaxy.mjs <source-id> <relative-root> <output-path>");
```

- [ ] **Step 6: 修正 analyze-catalog.mjs 的 usage 字符串**

```javascript
// 第 142 行：
throw new Error("Usage: node tools/analysis/analyze-catalog.mjs <source-id> <relative-root> <pattern> <output-path>");
```

- [ ] **Step 7: 修正 extract-catalog-boundary.mjs 的 usage 字符串**

```javascript
// 第 276 行：
throw new Error("Usage: node tools/analysis/extract-catalog-boundary.mjs <recipe-path>");
```

- [ ] **Step 8: 修正 compare-catalog-chains.mjs 的 usage 字符串**

```javascript
// 第 113 行：
throw new Error("Usage: node tools/analysis/compare-catalog-chains.mjs <recipe-path> <generated-source-id> <output-path>");
```

- [ ] **Step 9: 验证路径修复**

Run: `node tools/analysis/analyze-galaxy.mjs --composition src/projects/cmre-porting/manifests/composition.json /tmp/test-galaxy.json`
Expected: 运行成功无路径错误

---

## Task 2: analyze-galaxy.mjs 输出对齐 dependency-graph schema

**Files:**
- Modify: `tools/analysis/analyze-galaxy.mjs` (核心重构)

- [ ] **Step 1: 重构 runAnalysis 函数的输出构建**

```javascript
async function runAnalysis(packages, outputPath, meta) {
  // ... 前半部分不变（收集 records, definitions, calls）
  
  // ===== 新增：构建 nodes =====
  const nodes = records.map((record) => ({
    id: record.path,
    kind: "galaxy-library",
    path: record.path,
    metadata: {
      packageId: record.packageId,
      bytes: record.bytes,
      parseErrors: record.parseErrors,
      functions: record.functions,
      calls: record.calls,
      apiCalls: record.apiCalls
    }
  }));
  
  // ===== 新增：构建 edges =====
  const edges = [];
  
  // include 边
  for (const record of records) {
    for (const include of record.includes) {
      const target = resolveInclude(record.path, include.target, fileIndex, suffixIndex);
      if (target) {
        edges.push({
          from: record.path,
          to: target,
          relation: "includes",
          evidence: [`${record.path}:${include.line}`]
        });
      }
    }
  }
  
  // 跨文件调用边
  for (const call of calls) {
    const targets = definitions.get(call.callee) ?? [];
    const otherFiles = [...new Set(targets.map((t) => t.file).filter((f) => f !== call.file))];
    for (const target of otherFiles) {
      edges.push({
        from: call.file,
        to: target,
        relation: "calls",
        evidence: [`${call.callee}@${call.file}:${call.line}`]
      });
    }
  }
  
  // API 调用边（trigger/bank/objective/reward/initializer）
  for (const record of records) {
    for (const category of ["trigger", "bank", "objective", "reward", "initializer"]) {
      const relationMap = {
        trigger: "registers",
        bank: "reads",
        objective: "activates",
        reward: "rewards",
        initializer: "initializes"
      };
      for (const apiCall of record.apiCalls[category]) {
        edges.push({
          from: record.path,
          to: apiCall.name,
          relation: relationMap[category],
          evidence: [`${apiCall.name}@${record.path}:${apiCall.line}`]
        });
      }
    }
  }
  
  // ===== 新增：构建 unresolved =====
  const unresolved = [];
  for (const include of unresolvedIncludes) {
    unresolved.push({
      description: `Unresolved include: ${include.include} from ${include.from}`,
      requiredEvidence: "static"
    });
  }
  for (const item of unresolvedProjectCalls.values()) {
    unresolved.push({
      description: `Unresolved call: ${item.symbol} in ${item.file} (${item.count} occurrences)`,
      requiredEvidence: "static"
    });
  }
  
  // ===== 重构 result =====
  const result = {
    schemaVersion: 1,
    composition: meta.compositionId,
    nodes,
    edges,
    unresolved,
    
    // 保留向后兼容字段
    analyzer: "sc2-galaxy-lang.Parser",
    sourceId: meta.sourceId ?? null,
    root: meta.root || ".",
    packages: packages.map((p) => ({ packageId: p.packageId, sourceId: p.sourceId })),
    summary: {
      packages: packages.length,
      files: records.length,
      bytes: records.reduce((sum, r) => sum + r.bytes, 0),
      parseErrors: records.reduce((sum, r) => sum + r.parseErrors, 0),
      functions: records.reduce((sum, r) => sum + r.functions, 0),
      calls: records.reduce((sum, r) => sum + r.calls, 0),
      includeEdges: includeEdges.length,
      unresolvedIncludes: unresolvedIncludes.length,
      crossFileCallEdges: crossFile.size,
      unresolvedProjectCalls: unresolvedProjectCalls.size
    },
    files: records,
    includeEdges,
    crossFileCalls: [...crossFile.values()].map((e) => ({ ...e, symbols: [...e.symbols].sort() })),
    unresolvedProjectCalls: [...unresolvedProjectCalls.values()].sort((a, b) => b.count - a.count),
    unresolvedProjectCallsByPackage: [...unresolvedByPackage.entries()]
      .map(([pkgId, items]) => ({
        packageId: pkgId,
        unresolvedCount: items.length,
        callSiteCount: items.reduce((sum, i) => sum + i.count, 0),
        symbols: items.map((i) => ({ symbol: i.symbol, count: i.count })).sort((a, b) => b.count - a.count)
      }))
      .sort((a, b) => b.unresolvedCount - a.unresolvedCount)
  };
  
  // ... 写入文件部分不变
}
```

- [ ] **Step 2: 验证输出格式**

Run: `node tools/analysis/analyze-galaxy.mjs --composition src/projects/cmre-porting/manifests/composition.json /tmp/test-galaxy.json`
Expected: 输出包含 `nodes`, `edges`, `unresolved` 字段且符合 schema

---

## Task 3: analyze-catalog.mjs 输出对齐 dependency-graph schema

**Files:**
- Modify: `tools/analysis/analyze-catalog.mjs`

- [ ] **Step 1: 重构 analyze 函数的输出构建**

```javascript
async function analyze(sourceId, relativeRoot, patternText, outputPath) {
  // ... 前半部分不变（加载 XML、收集 entries、筛选 selectedEntries）
  
  // ===== 新增：构建 nodes =====
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
  
  // ===== 新增：构建 edges =====
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
  
  // ===== 重构 result =====
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
      .sort((a, b) => a.family.localeCompare(b.family) || a.id.localeCompare(b.id)),
    reverseReferences,
    caseCollisionRisks: [...caseGroups.entries()]
      .filter(([, values]) => values.size > 1)
      .map(([key, values]) => ({ family: key.split("\0")[0], ids: [...values].sort() })),
    parseErrors
  };
  
  // ... 写入文件部分不变
}
```

---

## Task 4: 新增 packaging-report.schema.json

**Files:**
- Create: `docs/schemas/packaging-report.schema.json`

- [ ] **Step 1: 创建 schema 文件**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "packaging-report.schema.json",
  "title": "Packaging Validation Report",
  "description": "SC2 包完整性校验报告，由 tools/analysis/validate-packaging.mjs 产生",
  "type": "object",
  "required": ["schemaVersion", "generatedAt", "compositionId", "summary", "checks"],
  "properties": {
    "$schema": { "type": "string" },
    "schemaVersion": { "const": 1 },
    "generatedAt": { "type": "string", "format": "date-time" },
    "compositionId": { "type": "string" },
    "summary": {
      "type": "object",
      "required": ["total", "passed", "failed", "warnings"],
      "properties": {
        "total": { "type": "integer", "minimum": 0 },
        "passed": { "type": "integer", "minimum": 0 },
        "failed": { "type": "integer", "minimum": 0 },
        "warnings": { "type": "integer", "minimum": 0 }
      },
      "additionalProperties": false
    },
    "checks": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "name", "status", "findings"],
        "properties": {
          "id": { "type": "string" },
          "name": { "type": "string" },
          "status": { "enum": ["pass", "fail", "warning"] },
          "findings": {
            "type": "array",
            "items": {
              "type": "object",
              "required": ["level", "message", "path"],
              "properties": {
                "level": { "enum": ["error", "warning", "info"] },
                "message": { "type": "string" },
                "path": { "type": "string" }
              },
              "additionalProperties": false
            }
          }
        },
        "additionalProperties": false
      }
    },
    "packages": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["packageId", "sourceId", "path", "exists"],
        "properties": {
          "packageId": { "type": "string" },
          "sourceId": { "type": "string" },
          "path": { "type": "string" },
          "exists": { "type": "boolean" },
          "declarations": {
            "type": "array",
            "items": {
              "type": "object",
              "required": ["name", "exists"],
              "properties": {
                "name": { "type": "string" },
                "exists": { "type": "boolean" },
                "path": { "type": "string" }
              },
              "additionalProperties": false
            }
          },
          "isMpq": { "type": "boolean" },
          "mpqValid": { "type": "boolean" }
        },
        "additionalProperties": false
      }
    }
  },
  "additionalProperties": false
}
```

---

## Task 5: 新增 validate-packaging.mjs

**Files:**
- Create: `tools/analysis/validate-packaging.mjs`

- [ ] **Step 1: 创建 packaging 校验器**

```javascript
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
      pkgInfo.mpqValid = null;
      continue;
    }
    const result = await runMpqVerify(pkgInfo.path);
    pkgInfo.mpqValid = result.valid;
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
```

---

## Task 6: 新增 validate-schema.mjs

**Files:**
- Create: `tools/analysis/validate-schema.mjs`

- [ ] **Step 1: 创建 schema 校验器**

```javascript
import { readFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(scriptDir, "..", "..");

async function readJson(path) {
  return JSON.parse(await readFile(path, "utf8"));
}

function validateType(value, typeDef, path) {
  if (typeDef === "string" && typeof value !== "string") return `Expected string at ${path}`;
  if (typeDef === "integer" && (!Number.isInteger(value) || typeof value !== "number")) return `Expected integer at ${path}`;
  if (typeDef === "boolean" && typeof value !== "boolean") return `Expected boolean at ${path}`;
  if (typeDef === "object" && (typeof value !== "object" || value === null || Array.isArray(value))) return `Expected object at ${path}`;
  if (typeDef === "array" && !Array.isArray(value)) return `Expected array at ${path}`;
  return null;
}

function validateEnum(value, enumValues, path) {
  if (!enumValues.includes(value)) return `Invalid value at ${path}: ${JSON.stringify(value)} must be one of ${JSON.stringify(enumValues)}`;
  return null;
}

function validateRequired(obj, required, path) {
  const missing = required.filter((prop) => !(prop in obj));
  if (missing.length > 0) return `Missing required properties at ${path}: ${missing.join(", ")}`;
  return null;
}

function validateAdditionalProperties(obj, additionalProps, path) {
  if (!additionalProps) {
    const extra = Object.keys(obj).filter((key) => key.startsWith("$"));
    if (extra.length > 0) return `Unexpected additional properties at ${path}: ${extra.join(", ")}`;
  }
  return null;
}

function validateSchema(obj, schema, path = "") {
  const errors = [];
  
  if (schema.required) {
    const err = validateRequired(obj, schema.required, path);
    if (err) errors.push(err);
  }
  
  if (schema.properties) {
    for (const [key, propSchema] of Object.entries(schema.properties)) {
      const value = obj[key];
      const propPath = path ? `${path}.${key}` : key;
      
      if (propSchema.const !== undefined && value !== propSchema.const) {
        errors.push(`Expected constant ${propSchema.const} at ${propPath}, got ${JSON.stringify(value)}`);
        continue;
      }
      
      if (value !== undefined) {
        if (propSchema.type) {
          const err = validateType(value, propSchema.type, propPath);
          if (err) errors.push(err);
        }
        
        if (propSchema.enum) {
          const err = validateEnum(value, propSchema.enum, propPath);
          if (err) errors.push(err);
        }
        
        if (propSchema.type === "array" && propSchema.items) {
          for (let i = 0; i < value.length; i++) {
            errors.push(...validateSchema(value[i], propSchema.items, `${propPath}[${i}]`));
          }
        }
        
        if (propSchema.type === "object" && propSchema.properties) {
          errors.push(...validateSchema(value, propSchema, propPath));
        }
      }
    }
  }
  
  if (schema.additionalProperties === false) {
    const err = validateAdditionalProperties(obj, false, path);
    if (err) errors.push(err);
  }
  
  return errors;
}

async function validateFile(dataPath, schemaPath) {
  const data = await readJson(resolve(repoRoot, dataPath));
  const schema = await readJson(resolve(repoRoot, schemaPath));
  const errors = validateSchema(data, schema);
  
  if (errors.length === 0) {
    console.log(`✓ ${dataPath} passes ${schemaPath}`);
    return { valid: true, errors: [] };
  } else {
    console.log(`✗ ${dataPath} fails ${schemaPath}:`);
    for (const err of errors) console.log(`  - ${err}`);
    return { valid: false, errors };
  }
}

async function main() {
  const args = process.argv.slice(2);
  if (args.length < 2) {
    throw new Error("Usage: node tools/analysis/validate-schema.mjs <data.json> <schema.json> [<data2.json> <schema2.json> ...]");
  }
  
  if (args.length % 2 !== 0) {
    throw new Error("Arguments must be pairs of <data.json> <schema.json>");
  }
  
  let allValid = true;
  for (let i = 0; i < args.length; i += 2) {
    const result = await validateFile(args[i], args[i + 1]);
    if (!result.valid) allValid = false;
  }
  
  process.exitCode = allValid ? 0 : 1;
}

main().catch((e) => {
  console.error("validate-schema failed: " + e.message);
  process.exitCode = 2;
});
```

---

## Task 7: 新增 static-validate.mjs 编排器

**Files:**
- Create: `tools/analysis/static-validate.mjs`

- [ ] **Step 1: 创建编排器**

```javascript
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
```

---

## Task 8: workspace.mjs 新增 static-validate 子命令

**Files:**
- Modify: `tools/utils/workspace.mjs`

- [ ] **Step 1: 新增 static-validate 子命令处理**

```javascript
async function staticValidateCommand(projectId, options) {
  const validateScript = join(scriptDir, "..", "analysis", "static-validate.mjs");
  if (!existsSync(validateScript)) throw new Error("static-validate.mjs 不存在: " + validateScript);
  
  const args = [validateScript];
  if (options.request) {
    args.push("--request", options.request);
    if (options.outDir) args.push("--out-dir", options.outDir);
  } else {
    args.push(projectId);
    if (options.stage) args.push("--stage", options.stage);
  }
  
  await runTool("node", args);
}
```

- [ ] **Step 2: 在命令分发中添加 static-validate**

```javascript
} else if (command === "static-validate") {
  // workspace.mjs static-validate <project-id> [--stage <stage-dir>]
  // workspace.mjs static-validate --request <request.json> --out-dir <dir>
  const opts = parseOptions(process.argv.slice(3));
  await staticValidateCommand(argument, opts);
} else if (command === "search") {
```

---

## Task 9: galaxy-lint.mjs 跨 mod 头文件注入改进

**Files:**
- Modify: `tools/analysis/galaxy-lint.mjs`

- [ ] **Step 1: 改进 findNativesFiles 函数，支持扫描 TriggerLibs 目录**

```javascript
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
        }
      }
    }
  } catch { /* 忽略配置读取失败，返回空列表 */ }
  return candidates;
}
```

- [ ] **Step 2: 在 lintFiles 函数中更新 s2workspace 构造，支持更多 lib 文件**

```javascript
// 在 lintFiles 函数中，s2workspace 构造部分修改为：
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
    for (const absFile of nativesFiles) {
      const relFile = normalizePath(repoRootPath, absFile);
      const sourceFile = documents.get(relFile);
      if (sourceFile) {
        const uriKey = "file:///" + absFile.replace(/\\/g, "/").replace(/^\//, "");
        documents.set(uriKey, sourceFile);
      }
    }
  }
}
```

---

## Task 10: 更新文档

**Files:**
- Modify: `docs/workflow.md`
- Modify: `tools/.codex/skills/sc2-static-analysis/SKILL.md`
- Modify: `tools/.codex/skills/sc2-static-analysis/references/output-contract.md`
- Modify: `tools/README.md`

- [ ] **Step 1: 更新 docs/workflow.md 的 stage 6 说明**

```markdown
6. `static-validation`: validate Galaxy, Catalog, dependencies, and packaging.
   - Run: `node tools/utils/workspace.mjs static-validate <project-id>`
   - Outputs: `evidence/static/diagnostics.json`, `evidence/static/dependency-graph.json`,
              `evidence/static/packaging-report.json`, `evidence/static/stage-verdict.json`
```

- [ ] **Step 2: 更新 SKILL.md 的用法说明**

```markdown
## 静态校验入口

```powershell
# 全项目静态校验
node tools/utils/workspace.mjs static-validate src/projects/<project-id>

# 声明式校验（按 static-analysis-request.json 指定）
node tools/utils/workspace.mjs static-validate --request <request.json> --out-dir <stage>/evidence/static

# 单独运行 galaxy-lint
node tools/utils/workspace.mjs lint src/projects/<project-id> --out evidence/static/diagnostics.json

# 单独运行 analyze-galaxy（输出符合 dependency-graph schema）
node tools/analysis/analyze-galaxy.mjs --composition <composition.json> <output-path>

# 单独运行 analyze-catalog（输出符合 dependency-graph schema）
node tools/analysis/analyze-catalog.mjs <source-id> <relative-root> <pattern> <output-path>

# 单独运行 packaging 校验
node tools/analysis/validate-packaging.mjs <composition.json> <output-path> [dependency-graph.json]

# 单独运行 schema 校验
node tools/analysis/validate-schema.mjs <data.json> <schema.json>
```
```

- [ ] **Step 3: 更新 output-contract.md**

```markdown
Store outputs under the active stage:

```text
evidence/static/
  dependency-graph.json      # 合并后的依赖图（符合 dependency-graph.schema.json）
  diagnostics.json           # Galaxy 语法/类型诊断（符合 static-diagnostics.schema.json）
  packaging-report.json      # Packaging 校验报告（符合 packaging-report.schema.json）
  analyzer-commands.json     # 执行的分析器命令列表
  unresolved.json            # 未解析依赖列表
  stage-verdict.json         # 阶段校验汇总（pass/fail）
```
```

- [ ] **Step 4: 更新 tools/README.md 的工具清单**

```markdown
├── analysis/         # 静态分析
│   ├── galaxy-lint.mjs            # Galaxy 语法+类型诊断（改进跨 mod 头文件注入）
│   ├── analyze-galaxy.mjs         # Galaxy 依赖图（输出符合 dependency-graph schema）
│   ├── analyze-catalog.mjs        # Catalog 分析（输出符合 dependency-graph schema）
│   ├── extract-catalog-boundary.mjs # Catalog 边界抽取
│   ├── compare-catalog-chains.mjs   # Catalog 链对比
│   ├── static-validate.mjs        # 静态校验编排器（新增）
│   ├── validate-packaging.mjs     # Packaging 校验器（新增）
│   └── validate-schema.mjs        # Schema 校验器（新增）
```
```

---

## Self-Review

### 1. Spec Coverage

| 设计节 | 对应任务 |
|--------|----------|
| §1 路径修复 | Task 1 |
| §2 analyze-galaxy 输出对齐 schema | Task 2 |
| §3 analyze-catalog 输出对齐 schema | Task 3 |
| §4 static-validate 编排器 | Task 7 + Task 8 |
| §5 validate-packaging + schema | Task 4 + Task 5 |
| §6 validate-schema | Task 6 |
| §7 galaxy-lint 头文件注入 | Task 9 |
| 文档更新 | Task 10 |

✓ 全部覆盖

### 2. Placeholder Scan

无 `TBD`、`TODO`、占位符。✓

### 3. Type Consistency

- `dependency-graph.schema.json` 的 `nodes[].kind` 枚举值：`galaxy-library`, `catalog-entry` ✓
- `edges[].relation` 枚举值：`includes`, `calls`, `registers`, `reads`, `activates`, `rewards`, `initializes`, `depends-on` ✓
- `unresolved[].requiredEvidence`：`static` ✓

✓ 类型一致

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-23-static-validation-enhancement.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
