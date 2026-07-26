# 完善工作流静态校验部分 - 设计文档

## 背景与问题

当前 SC2 移植工作流的静态校验部分存在以下问题：

1. **阻断性路径 bug**：4 个分析器（`analyze-galaxy.mjs`、`analyze-catalog.mjs`、`extract-catalog-boundary.mjs`、`compare-catalog-chains.mjs`）使用错误的配置路径 `config/workspace.json`，实际配置在 `src/config/workspace.json`，导致这些分析器当前无法运行。

2. **语义鸿沟**：`analyze-galaxy.mjs` 和 `analyze-catalog.mjs` 的输出格式与 `dependency-graph.schema.json` 要求的 `{nodes, edges, unresolved}` 结构不匹配，分析器产物无法直接作为合规的依赖图证据。

3. **编排缺口**：`workspace.mjs` 只有 `lint` 子命令；workflow stage 6 `static-validation` 要求"validate Galaxy, Catalog, dependencies, and packaging"，但缺乏统一入口一次性执行全套校验。

4. **packaging 校验缺失**：stage 6 提到的 packaging 校验无对应工具实现。

5. **schema 校验缺失**：分析器输出未校验是否符合 schema。

6. **galaxy-lint 跨 mod 头文件注入限制**：当前只注入 `natives.galaxy`/`natives_missing.galaxy`，无法解析跨 lib 的 include 引用。

## 设计目标

1. 修复阻断性路径 bug，使所有分析器可运行
2. 让 `analyze-galaxy.mjs` 和 `analyze-catalog.mjs` 输出符合 `dependency-graph.schema.json` 的结构
3. 新增 `static-validate` 编排器，提供 stage 6 统一入口
4. 实现 packaging 三项综合校验（composition 包完整性、文档声明文件校验、MPQ 结构校验）
5. 新增 schema 校验器，确保产物合规
6. 改进 galaxy-lint 的跨 mod 头文件注入能力

## 架构设计

```
workspace.mjs static-validate <project-id>
    |
    v
tools/analysis/static-validate.mjs
    |
    +-- galaxy-lint.mjs (改进头文件注入)
    +-- analyze-galaxy.mjs (输出对齐 dependency-graph schema)
    +-- analyze-catalog.mjs (输出对齐 dependency-graph schema)
    +-- validate-packaging.mjs (新增)
    +-- validate-schema.mjs (新增)
    |
    v
evidence/static/
    diagnostics.json
    dependency-graph.json
    packaging-report.json
    analyzer-commands.json
    unresolved.json
    stage-verdict.json
```

## 详细设计

### §1. 修复分析器配置路径

- **目标**：4 个分析器使用正确的 `src/config/workspace.json` 路径
- **改动**：将 `analyze-galaxy.mjs`、`analyze-catalog.mjs`、`extract-catalog-boundary.mjs`、`compare-catalog-chains.mjs` 中的 `join(repoRoot, "config", ...)` 改为 `join(repoRoot, "src", "config", ...)`
- **附带修正**：同步修正文件末尾 usage 字符串中残留的 `scripts/analyze-*.mjs` → `tools/analysis/analyze-*.mjs`

### §2. analyze-galaxy.mjs 输出对齐 dependency-graph schema

- **目标**：直接输出符合 `dependency-graph.schema.json` 的 `{schemaVersion, composition, nodes, edges, unresolved}` 结构
- **映射规则**：
  - `.galaxy` 文件 → `node{kind:"galaxy-library", path, metadata:{packageId, bytes, functions, calls, parseErrors, apiCalls}}`
  - include 边 → `edge{relation:"includes", from:源文件, to:目标文件, evidence:[file:line]}`
  - 跨文件调用 → `edge{relation:"calls", from:调用文件, to:定义文件, evidence:[symbols, line]}`
  - apiCalls.trigger → `edge{relation:"registers", evidence:[name, line]}`
  - apiCalls.bank → `edge{relation:"reads"|"writes", evidence:[name, line]}`
  - apiCalls.objective → `edge{relation:"activates", evidence:[name, line]}`
  - apiCalls.reward → `edge{relation:"rewards", evidence:[name, line]}`
  - apiCalls.initializer → `edge{relation:"initializes", evidence:[name, line]}`
  - unresolvedIncludes + unresolvedProjectCalls → `unresolved[]{description, requiredEvidence:"static"}`
- **兼容性**：保留原有 `summary`、`files`、`includeEdges`、`crossFileCalls` 等字段（放在 `metadata` 或作为 additionalProperties），确保向后兼容。

### §3. analyze-catalog.mjs 输出对齐 dependency-graph schema

- **目标**：保留 pattern 筛选模式，输出符合 dependency-graph 的子图结构
- **映射规则**：
  - 每个 catalog entry → `node{kind:"catalog-entry", path:sourceUri, metadata:{family, ctype, parent}}`
  - parent 继承 → `edge{relation:"depends-on", from:子项, to:父项}`
  - reverseReferences → `edge{relation:"depends-on", from:引用方, to:被引用}`
- **兼容性**：保留原有 `selectedEntries`、`reverseReferences`、`caseCollisionRisks`、`parseErrors` 字段。

### §4. static-validate 编排器（新增 tools/analysis/static-validate.mjs）

- **目标**：提供 stage 6 的统一编排入口
- **调用方式**：
  - 声明式：`node tools/utils/workspace.mjs static-validate --request <static-analysis-request.json> --out-dir <stage>/evidence/static`
  - 默认全跑：`node tools/utils/workspace.mjs static-validate <project-id> [--stage <stage-dir>]`
- **调度顺序**：
  1. galaxy-lint → `diagnostics.json`
  2. analyze-galaxy → `galaxy-graph.json`（合并为 dependency-graph 的一部分）
  3. analyze-catalog → `catalog-graph.json`（合并为 dependency-graph 的一部分）
  4. 合并子图为 `dependency-graph.json`
  5. validate-packaging → `packaging-report.json`
  6. validate-schema → 校验所有产物
  7. 汇总 `stage-verdict.json`（pass/fail 状态）
- **退出码**：全 pass 为 0，有 error 为 1

### §5. validate-packaging.mjs（新增）

- **目标**：实现 packaging 三项综合校验
- **校验项**：
  1. **composition 包完整性**：manifest 每个 package 的 sourceId+path 可解析且存在；dependency-graph 无未解析外部包
  2. **文档声明文件校验**：每个 mod/map 的 DocumentInfo、DocumentHeader、ComponentList.SC2Components、GameData.version、GameText.version 存在且可解析
  3. **MPQ 结构校验**：对 `.SC2Map`/`.SC2Mod` 文件调用 `tools/mpq/scripts/verify_mpq.py` 校验 MPQ 结构完整性
- **产出**：`packaging-report.json`，格式见新增的 `packaging-report.schema.json`

### §6. validate-schema.mjs（新增）

- **目标**：校验 `evidence/static/` 下所有产物符合对应 schema
- **校验规则**：
  - `diagnostics.json` ← `static-diagnostics.schema.json`
  - `dependency-graph.json` ← `dependency-graph.schema.json`
  - `packaging-report.json` ← `packaging-report.schema.json`
- **实现方式**：使用 Node 内置功能 + 手写最小校验器，按 schema 的 `required`、`type`、`enum`、`const`、`additionalProperties` 规则校验，避免新增外部依赖。

### §7. galaxy-lint.mjs 跨 mod 头文件注入改进

- **目标**：支持注入外部 `TriggerLibs/` 头文件，让 checker 能解析跨 lib 调用
- **改进方案**：扫描被分析文件 include 的 `lib*` 前缀，从 `official-data` 的 `TriggerLibs/` 目录加载对应 lib 头文件进入 host documents
- **保留限制**：单文件分析场景仍建议使用 `--no-type-check`，因为单文件无法提供完整的 host context

## 产出文件清单

### 修改文件
1. `tools/analysis/analyze-galaxy.mjs` - 路径修复 + 输出对齐 schema
2. `tools/analysis/analyze-catalog.mjs` - 路径修复 + 输出对齐 schema
3. `tools/analysis/extract-catalog-boundary.mjs` - 路径修复
4. `tools/analysis/compare-catalog-chains.mjs` - 路径修复
5. `tools/analysis/galaxy-lint.mjs` - 跨 mod 头文件注入改进
6. `tools/utils/workspace.mjs` - 新增 `static-validate` 子命令
7. `docs/workflow.md` - 更新 stage 6 说明
8. `tools/.codex/skills/sc2-static-analysis/SKILL.md` - 更新用法说明
9. `tools/.codex/skills/sc2-static-analysis/references/output-contract.md` - 更新输出契约
10. `tools/README.md` - 更新工具清单

### 新增文件
1. `tools/analysis/static-validate.mjs` - 静态校验编排器
2. `tools/analysis/validate-packaging.mjs` - packaging 校验器
3. `tools/analysis/validate-schema.mjs` - schema 校验器
4. `docs/schemas/packaging-report.schema.json` - packaging report 格式定义

## 验证方案

1. **路径修复验证**：运行 `node tools/analysis/analyze-galaxy.mjs --composition <composition.json> <out>` 确认不报错
2. **输出对齐验证**：用 `validate-schema.mjs` 校验 `analyze-galaxy.mjs` 输出符合 `dependency-graph.schema.json`
3. **编排器验证**：运行 `node tools/utils/workspace.mjs static-validate src/projects/cmre-porting` 验证端到端流程
4. **packaging 校验验证**：对已知项目运行 `validate-packaging.mjs`，确认三项校验正确识别问题
5. **schema 校验验证**：用 `validate-schema.mjs` 自校验所有产物 schema 合规性

## 风险与注意事项

1. **向后兼容**：分析器输出对齐 schema 时保留原有字段，确保历史 evidence 记录仍可读
2. **dependency-graph.schema.json 约束**：`additionalProperties: false` 要求输出严格符合 schema，需确保所有字段都在 schema 中定义
3. **galaxy-lint 性能**：跨 mod 头文件注入可能增加分析时间，建议对大项目使用 `--no-type-check` 快速模式
4. **MPQ 校验依赖**：`validate-packaging.mjs` 依赖 `verify_mpq.py`，需确保该脚本可用

## 验收标准

1. 所有分析器可正常运行（无路径错误）
2. `analyze-galaxy.mjs` 和 `analyze-catalog.mjs` 输出通过 schema 校验
3. `static-validate` 编排器可一次性运行全套校验并产出合规产物
4. packaging 三项校验均有实现并可独立运行
5. 文档已同步更新
