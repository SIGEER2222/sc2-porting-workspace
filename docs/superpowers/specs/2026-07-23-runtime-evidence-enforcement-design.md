# 运行时证据强制门禁 - 设计文档

## 背景与问题

当前 SC2 移植工作流对 AI 在"运行时验证"阶段的约束度不足。`AGENTS.md` 与 `docs/workflow.md`
已经写了 "Do not report completion from static analysis alone" / "dynamic verification
requires runtime evidence" / "active stage log must record the evidence path and command"
等软规则，但实际执行中出现以下反复问题：

1. **AI 跳过 runtime 验证直接宣称完成**：写 `result.json status=pass` 但 `evidence/runtime/` 目录为空。
2. **AI 用低强度证据冒充高强度证据**：用 replay-decode 顶替 live SC2 验证，且不标记降级。
3. **`stage-verdict.json` 是 AI 自写**：没有独立脚本复核证据真伪。
4. **门禁可被绕过**：AI 直接手写 `<next-stage>/plan.md` 即可推进，无强制 hook。
5. **stage 时间窗内的进程身份无法验证**：AI 宣称"在某时跑了某命令"，但无时间戳、无进程 ID、无产物 hash 关联。

## 设计目标

1. **强制力**：AI 无法绕过门禁宣称"运行时验证已通过"——必须由独立 reviewer 重跑命令并比对结果。
2. **可重跑**：runtime 证据文件必须含完整可重跑信息（命令、工作目录、环境变量、产物 hash）。
3. **不可降级冒充**：`evidence_strength` 强制枚举，不允许将 replay 证据标记为 live。
4. **阻断分层**：自检 → 推进门禁 → static-validate 集成 → pre-commit hook，四层互证。
5. **无人工签字兜底**：SC2 live 跑不通时直接 block，不允许 fallback 到 replay 作为 pass 证据。

## 系统边界

- 本设计仅约束 `sc2-porting-workspace` 仓库内的 stage 推进流程。
- 已存在的 `launch-sc2-with-api.ps1`（位于 `artifacts/`）已验证可直启 `SC2_x64.exe` 并开放 API 端口 5000，作为 SC2 live 启动的标准入口。
- 亡者之夜（NOTD）与"疯批帝国"作为 runtime 验证的标准目标场景（launcher 已能跑通）。

## 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│  stage N (runtime-validation)                                │
│                                                              │
│  AI 执行流程：                                                │
│  1. launch-sc2-with-api.ps1 [-MapPath ...] -Port 5000        │
│  2. sc2-observer.py --port 5000 --scenario <scenario.json>  │
│     --out-dir <stage>/evidence/runtime                       │
│     → 产出 verdict.json + events.ndjson                      │
│  3. AI 起草 result.json，填 evidence.runtime[]                │
│  4. node tools/runtime-bridge/review-runtime.mjs <stage-dir> │
│     ── 按 result.json 里每条 claim 重跑 command              │
│     ── 比对 exit_code / observed_values                       │
│     ── 输出 evidence/runtime/review-verdict.json             │
│  5. AI 检查 review-verdict，全 reproducible=true 才写         │
│     result.status=pass                                       │
│                                                              │
│  推进门禁（四层）：                                           │
│  层 1 - AI 自检：写 result.json 前必跑 reviewer              │
│  层 2 - advance-stage 命令：写下一 stage plan.md 前再跑一次  │
│  层 3 - static-validate 集成：下一 stage 校验前一 stage 证据  │
│  层 4 - pre-commit hook：commit 时校验文件存在 + schema       │
└─────────────────────────────────────────────────────────────┘
```

数据流三件套互相印证：
- `verdict.json`：单次 runtime 验证的原始证据（含可重跑命令、产物 hash、observed_values）
- `review-verdict.json`：reviewer 重跑后的复核结论（每条 claim 的 reproducible 判定）
- `result.json`：stage 总结，必须引用上述两个文件且 schema 校验通过

## 详细设计

### §1. runtime-verdict.json 强制字段（重构现有 schema）

**重构** `docs/schemas/runtime-verdict.schema.json`（已存在但字段结构不兼容，需破坏性重构）。
现有 schema 字段为 `scenarioId / runId / status / criteria[] / evidence[]`，重构后字段如下：

```json
{
  "schemaVersion": 1,
  "claim_id": "rt-001",
  "claim": "LibRuntimeUnitDetect.CountByType 能读到 player 1 的 SpawningPool",
  "command": "python sc2-observer.py --port 5000 --claim-id rt-001 --scenario scenarios/notd-player1-spawn.json --out-dir evidence/runtime",
  "working_dir": "e:/Code/MyMod/SC2VibeTools/sc2-porting-workspace",
  "env": {
    "PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION": "python",
    "SC2_LAUNCHER_PATH": "artifacts/launch-sc2-with-api.ps1"
  },
  "timeout_seconds": 180,
  "executed_at": "2026-07-23T15:42:11+08:00",
  "process_id": 12345,
  "exit_code": 0,
  "stdout_sha256": "abc123def4567890abcdef1234567890abcdef1234567890abcdef1234567890",
  "produced_files": [
    {
      "path": "evidence/runtime/rt-001-events.ndjson",
      "sha256": "def4567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
      "bytes": 8421
    }
  ],
  "observed_values": {
    "player_1": {"SpawningPool": 1, "Hatchery": 0},
    "api_status_sequence": [1, 2, 2, 3]
  },
  "evidence_strength": "live"
}
```

**多 claim 文件命名规则**：每条 claim 产出独立的 `<claim_id>-runtime-verdict.json` 与 `<claim-id>-events.ndjson`。sc2-observer.py 通过新参数 `--claim-id <id>` 指定输出文件名前缀，避免覆盖。

字段约束：
- `claim_id` 必须在当前 stage 目录下唯一
- `command` + `working_dir` + `env` 必须能让 reviewer 精确重跑
- `stdout_sha256` + `produced_files[].sha256`：**仅审计用，不参与 reviewer 比对**（因时间戳/临时目录会变）。保留用于事后人工审计与溯源
- `process_id`：**仅审计用**，进程已退出无法事后验证真伪
- `observed_values`：AI 宣称的观测值，是 reviewer 比对的核心字段
- `evidence_strength` 枚举：`live`（唯一允许进入 pass 候选） | `replay`（仅作为开发期参考，不允许标 pass） | `none`（永久 fail）
- `additionalProperties: false`

**sc2-observer.py 改动**：
- 新增 `--claim-id <id>` 参数：输出文件改为 `<claim-id>-runtime-verdict.json` + `<claim-id>-events.ndjson`
- verdict.json 内容必须包含上述所有强制字段（command / working_dir / env / timeout_seconds / executed_at / process_id / exit_code / stdout_sha256 / produced_files / observed_values / evidence_strength）
- sc2-observer.py 自身写入 `claim` 字段时复用 `--claim-id` 参数值；`claim` 文本由 `--scenario` 的 scenario.json 提供

### §2. review-verdict.json schema

新增 `docs/schemas/review-verdict.schema.json`：

```json
{
  "schemaVersion": 1,
  "reviewed_at": "2026-07-23T15:50:00+08:00",
  "reviewer_version": "0.1.0",
  "reviewer_command": "node tools/runtime-bridge/review-runtime.mjs src/projects/cmre-porting/stages/04-runtime-baseline",
  "claims": [
    {
      "claim_id": "rt-001",
      "claim": "LibRuntimeUnitDetect.CountByType 能读到 player 1 的 SpawningPool",
      "reproducible": true,
      "exit_code_match": true,
      "observed_values_match": true,
      "diff": null,
      "rerun_command": "python sc2-observer.py --port 5000 --claim-id rt-001 --scenario scenarios/notd-player1-spawn.json --out-dir evidence/runtime",
      "rerun_executed_at": "2026-07-23T15:48:22+08:00",
      "rerun_process_id": 23456,
      "rerun_exit_code": 0,
      "rerun_observed_values": {
        "player_1": {"SpawningPool": 1, "Hatchery": 0},
        "api_status_sequence": [1, 2, 2, 3]
      },
      "failure_reason": null
    }
  ],
  "summary": {
    "total": 3,
    "reproducible": 3,
    "partial": 0,
    "failed": 0
  }
}
```

**claim 级别状态映射**：
- `reproducible: true` → exit_code 一致 + observed_values 完全匹配
- `reproducible: false, failure_reason: "partial_match"` → exit_code 一致但 observed_values 缺字段或部分不匹配；`diff` 字段记录差异详情
- `reproducible: false, failure_reason: "sc2_unreachable" | "timeout" | "sc2_crashed" | "missing_artifact" | "non_live_strength"` → 容错分支，附 `diff: null`

退出码：`summary.reproducible == summary.total` 为 0，否则 1。

### §3. reviewer 行为（`tools/runtime-bridge/review-runtime.mjs`）

**输入**：stage 目录路径（绝对或相对 sc2-porting-workspace 根的路径）。
`workspace.mjs advance-stage <project-id>` 内部会读取 `<project-id>/project.json` 的 `currentStage` 字段，转换为 `<project-dir>/stages/<current-stage>` 后传给 reviewer。

**步骤**：
1. 读 `<stage>/result.json`，提取 `claims[]` 数组中所有 `type == "runtime"` 的 claim
2. 对每条 runtime claim：
   - 校验 `verdict_path`（指向 `<claim_id>-runtime-verdict.json`）文件存在且 schema 合规
   - 校验 `evidence_strength == "live"`（其他枚举值直接判 `reproducible: false, failure_reason: "non_live_strength"`）
   - **SC2 live 前置检查**：探测 127.0.0.1:5000 是否 LISTENING
     - 不在 → 调 `launch-sc2-with-api.ps1`，等待端口开放（最多 120s）
     - 仍失败 → 该 claim 标 `reproducible: false, failure_reason: "sc2_unreachable"`，**不 fallback 到 replay**
   - **重跑**：在 `working_dir` 下用 `env` 执行 `command`
     - 子进程超时默认 180s（可由 `timeout_seconds` 覆盖）
     - 捕获：`exit_code`、`stdout_sha256`、`produced_files[].sha256`（重新计算）、`observed_values`
     - `observed_values` 提取方式：sc2-observer.py 必须把关键字段写在重跑产物的 `observed_values` 节点下，reviewer 直接读重跑产物的 `observed_values` 节点；不走 JSONPath 提取以避免实现复杂度
3. 比对策略：
   - `exit_code` 必须一致（不一致 → `reproducible: false, failure_reason: "exit_code_mismatch"`）
   - `observed_values` 比对规则：
     - 数值/字符串 → 完全相等
     - 数组 → 长度相等 + 元素集合相等（顺序无关，因事件顺序可能因时序抖动）
     - 嵌套对象 → key 集合相等 + 每个 key 的值递归套用上述规则
     - 缺字段 → `reproducible: false, failure_reason: "partial_match"`，`diff` 字段记录缺失路径
   - `stdout_sha256` + `produced_files[].sha256`：**不参与比对**（仅审计用）
4. 输出 `<stage>/evidence/runtime/review-verdict.json`
5. 退出码：`summary.reproducible == summary.total` 为 0，否则 1

**容错**（全部标 `reproducible: false`，不降级）：
- 子进程超时 → 杀进程，`failure_reason: "timeout"`
- SC2 进程崩溃（端口监听后 SC2_x64.exe 不在）→ `failure_reason: "sc2_crashed"`，尝试重启一次后仍失败即终止
- 产物文件丢失 → `failure_reason: "missing_artifact"`
- 任何容错分支都不会自动降级到 replay

### §4. 四层阻断机制

**result.json schema 扩展**（重构现有 `docs/schemas/stage-result.schema.json`）：

现有 schema 的 `claims[]` 项有 `type / claim / evidence: string[]` 字段。本设计为 `type == "runtime"` 的 claim 追加强制字段：

```json
{
  "type": "runtime",
  "claim": "LibRuntimeUnitDetect.CountByType 能读到 player 1 的 SpawningPool",
  "evidence": ["evidence/runtime/rt-001-runtime-verdict.json"],
  "verdict_path": "evidence/runtime/rt-001-runtime-verdict.json",
  "evidence_strength": "live",
  "review_verdict_path": "evidence/runtime/review-verdict.json"
}
```

`stage-result.schema.json` 修改：当 `claim.type == "runtime"` 时，`verdict_path` / `evidence_strength` / `review_verdict_path` 为 required。`status == "passed"` 时所有 runtime claim 的 `evidence_strength` 必须为 `live`。

**层 1 — AI 自检（写 result.json 前）**
- AI 在 `<stage>/result.json` 起草阶段必须先跑 `node tools/runtime-bridge/review-runtime.mjs <stage-dir>`
- 若退出码非 0，`result.status` 只能填 `blocked` 或 `failed`，不能填 `passed`（注意：现有 schema 用 `passed` 而非 `pass`）
- schema 校验 `review_verdict_path` 指向的文件存在且 `summary.reproducible == summary.total`

**层 2 — stage 推进门禁（`workspace.mjs advance-stage`）**
- 新增子命令 `advance-stage <project-id>`：
  1. 读取 `<project>/project.json` 的 `currentStage`，定位到 stage 目录
  2. 校验当前 stage `result.json` schema 合规
  3. 调 `review-runtime.mjs <stage-dir>` 二次复核（防止 AI 在自检后篡改 verdict.json）
  4. 调 `validate-schema.mjs` 校验三件套互相印证
  5. 全过 → 创建 `<next-stage>/plan.md` 骨架，写 `stage-transition.json`
  6. 任一不通过 → exit 1，输出失败 claim 列表
- AI 不能直接手写 `<next-stage>/plan.md` 绕过：`validate-schema.mjs` 会检查 `stage-transition.json` 是否存在；缺即视为非法推进

**`stage-transition.json` 字段结构**（由 advance-stage 命令生成，AI 不允许手写）：
```json
{
  "schemaVersion": 1,
  "from_stage": "04-runtime-baseline",
  "to_stage": "05-acceptance",
  "transitioned_at": "2026-07-23T16:00:00+08:00",
  "executor_pid": 5678,
  "review_verdict_sha256": "abc123...",
  "result_sha256": "def456...",
  "advance_stage_version": "0.1.0"
}
```
`stage-transition.json` 由 advance-stage 命令独占写权。validate-schema.mjs 校验该文件存在且 `review_verdict_sha256` 与磁盘上的 review-verdict.json 内容一致、`result_sha256` 与磁盘 result.json 内容一致。

**层 3 — static-validate 集成（内容校验）**
- `static-validate.mjs` 在原有 6 项检查后追加第 7 项："前一 stage 的 runtime review-verdict 必须存在且 reproducible=true"
- 该层会校验 `stage-transition.json` 的 sha256 字段与磁盘文件一致
- 即使 AI 完全跳过 `advance-stage`，跑到下一 stage 的 static-validate 时仍会被拦下

**层 4 — pre-commit hook（轻量存在性校验，弱于层 3）**
- 安装：`tools/utils/install-hooks.mjs` 一键安装到 `.git/hooks/pre-commit`
- hook 内容（**只做文件存在性 + JSON 字段读取，不做完整 schema 校验，不调 sha256 比对，不调 SC2**）：
  - 扫描 `src/projects/*/stages/*/` 下所有 stage 目录
  - 检查 git diff 里是否有 stage 目录下 `result.json` 被改为 `status: "passed"`
  - 若有，读取该 result.json，对每条 `type == "runtime"` 的 claim：
    - 校验 `verdict_path` 文件存在
    - 校验 `review_verdict_path` 文件存在
    - 读取 review-verdict.json，校验 `summary.reproducible == summary.total`
  - 检查 git diff 里是否有新增 `stages/<N>-<name>/plan.md`：若有，校验前一 stage 目录下 `stage-transition.json` 文件存在
  - 不通过 → 拒绝 commit（exit 1），打印缺失文件清单
- **明示弱于层 3**：layer 4 只校验文件存在 + summary 数字，不校验 stage-transition.json 的 sha256 与磁盘一致；AI 若手写 stage-transition.json，layer 4 不能发现，但 layer 3 会发现
- 性能：只做文件存在性 + JSON 字段读取，预计 < 500ms
- 绕过提示：hook 末尾打印 "若需绕过（仅紧急修复），用 git commit --no-verify"，并在 commit message 里要求写 `[manual-override]` 标记，便于事后审计

### §5. fallback 与降级规则

**不允许降级**：
- `evidence_strength: live` 是唯一允许进入 `passed` 候选的强度
- SC2 live 跑不通 → claim 直接标 `reproducible: false, failure_reason: "sc2_unreachable"`（或对应容错分支），result.status 不能为 `passed`，stage 不能 advance
- `replay` 强度仅作为开发期探索或 debug 辅助，不进入 `evidence/runtime/` 目录
- `none` 永远不允许标 `passed`

**replay-decode 的位置**：
- replay-probe.py 仍保留在 `tools/runtime-bridge/`，但产物只能写到 `evidence/dev/` 或临时目录
- `result.json` schema 校验所有 runtime claim 的 `evidence_strength != "replay"`，违反即 schema fail

**stage 失败时的回退路径**：
- AI 在 `<stage>/issues.json` 里记录 SC2 不可达的原因（如 "Battle.net Agent not running"）
- 用户修复环境后，AI 重跑 reviewer，无需重写整个 stage

### §6. 测试方案

**reviewer 自身的可信度**——三层测试：

1. **单元测试**（`test/test_review_runtime.mjs`）：
   - mock fixture：构造一个 fake `command`（如 `node -e "console.log('ok')"`）+ 期望 `observed_values`，验证 reviewer 能正确判定 `reproducible=true`
   - fail fixture：mock 一个返回不同 observed_values 的命令，验证 reviewer 正确判定 `reproducible=false, failure_reason: "partial_match"` 并产出 diff
   - 容错分支：超时（`failure_reason: "timeout"`）、SC2 端口不开（`failure_reason: "sc2_unreachable"`）、产物文件丢失（`failure_reason: "missing_artifact"`）、`evidence_strength != "live"`（`failure_reason: "non_live_strength"`），每分支一个 fixture

2. **集成测试**（`test/integration/test_review_runtime_live.mjs`，标记 `@integration`）：
   - 真实跑 SC2 live：用 `launch-sc2-with-api.ps1` 启动 → 用 `sc2-observer.py --claim-id rt-test --scenario scenarios/notd-ping.json --out-dir <tmp>` 跑一个最小 scenario（如 "ping SC2 API" 或亡者之夜场景的轻量断言）→ reviewer 重跑 → 验证 `reproducible=true`
   - 亡者之夜（NOTD）地图作为标准测试场景之一，验证 sc2-observer.py 能正确读取单位/建筑信息并写入 `rt-test-runtime-verdict.json`
   - 需要 SC2 已装，CI 跳过；本地手动跑

3. **E2E 验收**（手动）：
   - 在 cmre-porting 的 stage 04-runtime-baseline 上真实跑一次：AI 写 result.json → reviewer 复核 → advance-stage 推进 → pre-commit hook 拦截一次"伪造 passed"的尝试
   - 验收通过后此设计才算"已落地"

**schema 自校验**：
- `runtime-verdict.schema.json`（重构版）用 ajv 或自写最小校验器自校验
- `review-verdict.schema.json` 用同一 schema 体系
- `validate-schema.mjs` 把重构后的 runtime-verdict schema + 新增 review-verdict schema 加入校验清单

## 产出文件清单

### 修改文件
1. `docs/workflow.md` — 在 stage 7 后插入 stage 7.5: runtime-review
2. `AGENTS.md` — 增补 "Runtime Evidence Enforcement" 一节，明令违反即视为未完成
3. `tools/utils/workspace.mjs` — 新增 `advance-stage` 子命令
4. `tools/analysis/static-validate.mjs` — 追加第 7 项检查（前一 stage runtime review-verdict 校验 + stage-transition.json sha256 校验）
5. `tools/analysis/validate-schema.mjs` — 加入重构后的 runtime-verdict schema + 新增 review-verdict schema 校验；新增 stage-transition.json sha256 一致性校验逻辑
6. `tools/.codex/skills/sc2-static-analysis/SKILL.md` — 同步说明
7. `tools/.codex/skills/sc2-static-analysis/references/output-contract.md` — 同步契约
8. `docs/schemas/runtime-verdict.schema.json` — **重构**现有 schema（破坏性变更，字段全替换）
9. `docs/schemas/stage-result.schema.json` — 扩展 `claims[]` 为 `type == "runtime"` 的 claim 追加 `verdict_path / evidence_strength / review_verdict_path` required 字段
10. `tools/runtime-bridge/sc2-observer.py` — 新增 `--claim-id <id>` 参数；输出文件改为 `<claim-id>-runtime-verdict.json` + `<claim-id>-events.ndjson`；verdict.json 内容写入新 schema 所有强制字段

### 新增文件
1. `tools/runtime-bridge/review-runtime.mjs` — reviewer 主程序
2. `tools/utils/install-hooks.mjs` — pre-commit hook 安装器
3. `.git/hooks/pre-commit` — 由 install-hooks.mjs 生成（不直接 commit）
4. `docs/schemas/review-verdict.schema.json` — review-verdict schema（全新）
5. `docs/schemas/stage-transition.schema.json` — stage-transition schema（全新，约束 advance-stage 产出）
6. `test/test_review_runtime.mjs` — 单元测试
7. `test/integration/test_review_runtime_live.mjs` — 集成测试

## 风险与注意事项

1. **reviewer 自身的可信度**：reviewer 是用来约束 AI 的，但 reviewer 自己可能有 bug。三层测试 + schema 自校验保证其可信。
2. **SC2 live 启动依赖**：本设计的硬约束是 SC2 必须能跑 live。如果某次环境损坏（Battle.net Agent 异常等），整个 stage 流程会被 block。这是设计选择——宁可 block 也不允许伪造证据。
3. **pre-commit hook 性能**：< 500ms 目标通过轻量校验达成，不调用 SC2。
4. **stage-transition.json 缺失绕过**：AI 可能手写 stage-transition.json。layer 4 (pre-commit) 不能发现（只校验文件存在），但 layer 3 (static-validate) 会校验 `review_verdict_sha256` 与磁盘 review-verdict.json 内容一致，能发现伪造。
5. **observed_values 比对脆弱性**：若 sc2-observer.py 输出顺序不稳定，比对会失败。设计已用"集合相等"而非"数组相等"缓解，但极端情况下仍可能 partial_match。
6. **现有 evidence 文件不合规**：当前 `evidence/runtime-probe/` 下用 replay-decode 产生的 verdict.json 不符合新 schema，需在落地时迁移或归档为 `evidence/dev/`。
7. **runtime-verdict.schema.json 重构破坏性**：现有 schema 被重构后，所有引用旧 schema 的代码（如 replay-probe.py）需要同步修改或归档。
8. **stage-verdict.json 与 result.json 的角色区分**：
   - `stage-verdict.json`：由 `static-validate.mjs` 生成的**静态校验总结**，记录 6+1 项静态检查结果
   - `result.json`：按 `stage-result.schema.json` 约束的 **stage 完成总结**，含 claims / outputs / validation / status
   - 两者是不同文件、不同用途。本设计约束的是 `result.json`（claims 里 type=runtime 的部分），不修改 `stage-verdict.json` 的生成逻辑
   - 背景问题第 3 条提到的"stage-verdict.json 是 AI 自写"是历史问题，本设计通过 layer 3 让 static-validate 第 7 项校验前一 stage 的 runtime 证据，间接覆盖此风险

## 验收标准

1. 重构后的 `runtime-verdict.schema.json` + 新增 `review-verdict.schema.json` + `stage-transition.schema.json` 通过 ajv 自校验
2. 扩展后的 `stage-result.schema.json` 通过 ajv 自校验
3. `review-runtime.mjs` 单元测试 100% 通过（含容错分支 fixture：timeout / sc2_unreachable / missing_artifact / non_live_strength / partial_match）
4. `sc2-observer.py --claim-id rt-test` 能正确输出 `rt-test-runtime-verdict.json` + `rt-test-events.ndjson`，且 verdict.json 通过重构后的 schema 校验
5. `review-runtime.mjs` 在 cmre-porting stage 04-runtime-baseline 上集成测试通过：能正确判定 reproducible=true
6. E2E 验收：AI 试图伪造 `result.status=passed` 但 `review-verdict.json` 不存在时，pre-commit hook 拒绝 commit
7. E2E 验收：AI 试图手写 `<next-stage>/plan.md` + 伪造 `stage-transition.json` 但 sha256 不一致时，static-validate 第 7 项检查 fail
8. `AGENTS.md` 与 `docs/workflow.md` 已同步更新
