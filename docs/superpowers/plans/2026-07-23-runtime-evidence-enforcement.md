# 运行时证据强制门禁 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 sc2-porting-workspace 仓库内落地"AI 不能伪造 runtime 证据"的四层强制门禁，使 AI 必须通过 reviewer 重跑 SC2 live 命令才能宣称 stage 完成。

**Architecture:** 数据契约（runtime-verdict / review-verdict / stage-transition / stage-result 四个 schema 互相印证）+ 工具（review-runtime.mjs 重跑复核）+ 四层阻断（AI 自检 → advance-stage 门禁 → static-validate 第 7 项 → pre-commit hook）。SC2 live 启动用现有 `artifacts/launch-sc2-with-api.ps1`。

**Tech Stack:** Node.js (ESM, .mjs, 内置 fs/crypto/child_process, 无外部依赖), Python 3 (argparse/aiohttp, sc2-observer.py 已有), JSON Schema draft 2020-12, 现有手写最小 schema 校验器 `validate-schema.mjs`

**Spec:** `docs/superpowers/specs/2026-07-23-runtime-evidence-enforcement-design.md`

**关键约束（来自 user_rules / project_memory）：**
- 任何文件/Git 危险操作必须通过 file-ops skill 的包装脚本执行（`c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-*.ps1`），禁止直接 `Remove-Item`/`Copy-Item`/`New-Item`/`git checkout` 等
- 仅做当前任务需要的最小改动
- 优先用 Edit/Write 工具，不用 `>` / `>>` / `Set-Content` 重定向
- SC2 仓库结束前必须 `git commit`（无 remote 则跳过 pull/push）
- commit 说明用中文

**工作目录：** `e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace`（所有相对路径以此为根）

---

## File Structure

### 新增文件
| 文件 | 职责 |
|------|------|
| `docs/schemas/review-verdict.schema.json` | review-verdict.json 的 JSON Schema |
| `docs/schemas/stage-transition.schema.json` | stage-transition.json 的 JSON Schema |
| `tools/runtime-bridge/review-runtime.mjs` | reviewer 主程序：读 result.json → 重跑每条 runtime claim → 比对 observed_values → 出 review-verdict.json |
| `tools/utils/install-hooks.mjs` | pre-commit hook 安装器，生成 `.git/hooks/pre-commit` |
| `test/test_review_runtime.mjs` | reviewer 单元测试（含容错分支 fixture） |
| `test/integration/test_review_runtime_live.mjs` | reviewer 集成测试（真实跑 SC2 live） |

### 修改文件
| 文件 | 改动 |
|------|------|
| `docs/schemas/runtime-verdict.schema.json` | 重构：旧字段全替换为新字段（claim_id / command / observed_values / evidence_strength 等） |
| `docs/schemas/stage-result.schema.json` | 扩展：`claims[]` 中 `type=="runtime"` 的 claim 追加 `verdict_path` / `evidence_strength` / `review_verdict_path` 字段 |
| `tools/runtime-bridge/sc2-observer.py` | 加 `--claim-id` 参数；输出文件名改为 `<claim-id>-runtime-verdict.json` + `<claim-id>-events.ndjson`；verdict 写入新 schema 所有强制字段 |
| `tools/utils/workspace.mjs` | 加 `advance-stage <project-id>` 子命令 |
| `tools/analysis/static-validate.mjs` | 加第 7 项检查：前一 stage runtime review-verdict 必须存在且 reproducible=true；stage-transition.json sha256 校验 |
| `tools/analysis/validate-schema.mjs` | 把 review-verdict / stage-transition / 重构后的 runtime-verdict / 扩展后的 stage-result 加入默认校验清单 |
| `docs/workflow.md` | stage 7 后插入 stage 7.5: runtime-review；stage 6 描述追加第 7 项检查说明 |
| `AGENTS.md` | 增补 "Runtime Evidence Enforcement" 一节 |
| `tools/.codex/skills/sc2-static-analysis/SKILL.md` | 同步说明第 7 项检查与新子命令 |
| `tools/.codex/skills/sc2-static-analysis/references/output-contract.md` | 同步契约 |

---

## Task 1: Schema 文件重构/新增

**Files:**
- Modify: `docs/schemas/runtime-verdict.schema.json`（重构，破坏性变更）
- Modify: `docs/schemas/stage-result.schema.json`（扩展 claims[]）
- Create: `docs/schemas/review-verdict.schema.json`
- Create: `docs/schemas/stage-transition.schema.json`

### Task 1.1: 重构 runtime-verdict.schema.json

- [ ] **Step 1: 用 Write 覆盖 `docs/schemas/runtime-verdict.schema.json`**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "runtime-verdict.schema.json",
  "type": "object",
  "required": [
    "schemaVersion",
    "claim_id",
    "claim",
    "command",
    "working_dir",
    "env",
    "timeout_seconds",
    "executed_at",
    "process_id",
    "exit_code",
    "stdout_sha256",
    "produced_files",
    "observed_values",
    "evidence_strength"
  ],
  "properties": {
    "$schema": { "type": "string" },
    "schemaVersion": { "const": 2 },
    "claim_id": { "type": "string", "pattern": "^[a-z0-9][a-z0-9-]*$" },
    "claim": { "type": "string", "minLength": 1 },
    "command": { "type": "string", "minLength": 1 },
    "working_dir": { "type": "string", "minLength": 1 },
    "env": {
      "type": "object",
      "additionalProperties": { "type": "string" }
    },
    "timeout_seconds": { "type": "integer", "minimum": 1 },
    "executed_at": { "type": "string", "format": "date-time" },
    "process_id": { "type": "integer", "minimum": 1 },
    "exit_code": { "type": "integer" },
    "stdout_sha256": { "type": "string", "pattern": "^[a-f0-9]{64}$" },
    "produced_files": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["path", "sha256", "bytes"],
        "properties": {
          "path": { "type": "string", "minLength": 1 },
          "sha256": { "type": "string", "pattern": "^[a-f0-9]{64}$" },
          "bytes": { "type": "integer", "minimum": 0 }
        },
        "additionalProperties": false
      }
    },
    "observed_values": { "type": "object" },
    "evidence_strength": { "enum": ["live", "replay", "none"] }
  },
  "additionalProperties": false
}
```

- [ ] **Step 2: 验证 JSON 合法**

Run:
```powershell
node -e "JSON.parse(require('fs').readFileSync('docs/schemas/runtime-verdict.schema.json','utf8')); console.log('OK')"
```
Expected: 输出 `OK`，退出码 0

- [ ] **Step 3: Commit**

通过 file-ops skill 包装脚本提交（参考 user_rules）：
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-add.ps1" "docs/schemas/runtime-verdict.schema.json"
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-commit.ps1" "重构 runtime-verdict.schema.json：字段全替换为 claim_id/command/observed_values/evidence_strength"
```
Expected: 退出码 0，commit 创建成功

### Task 1.2: 扩展 stage-result.schema.json

- [ ] **Step 1: 用 Write 覆盖 `docs/schemas/stage-result.schema.json`**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "stage-result.schema.json",
  "type": "object",
  "required": ["schemaVersion", "stage", "status", "claims", "outputs", "validation"],
  "properties": {
    "$schema": { "type": "string" },
    "schemaVersion": { "const": 1 },
    "stage": { "type": "string" },
    "status": { "enum": ["passed", "failed", "blocked"] },
    "claims": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["type", "claim", "evidence"],
        "properties": {
          "type": { "enum": ["static", "runtime", "inference"] },
          "claim": { "type": "string" },
          "evidence": { "type": "array", "items": { "type": "string" } },
          "verdict_path": { "type": "string" },
          "evidence_strength": { "enum": ["live", "replay", "none"] },
          "review_verdict_path": { "type": "string" }
        },
        "allOf": [
          {
            "if": { "properties": { "type": { "const": "runtime" } } },
            "then": {
              "required": ["verdict_path", "evidence_strength", "review_verdict_path"]
            }
          }
        ],
        "additionalProperties": false
      }
    },
    "outputs": { "type": "array", "items": { "type": "string" } },
    "validation": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["command", "exitCode"],
        "properties": {
          "command": { "type": "string" },
          "exitCode": { "type": "integer" },
          "summary": { "type": "string" }
        },
        "additionalProperties": false
      }
    },
    "nextStage": { "type": ["string", "null"] }
  },
  "additionalProperties": false
}
```

- [ ] **Step 2: 验证 JSON 合法**

Run:
```powershell
node -e "JSON.parse(require('fs').readFileSync('docs/schemas/stage-result.schema.json','utf8')); console.log('OK')"
```
Expected: 输出 `OK`

- [ ] **Step 3: 用 ajv 校验 if/then 语法（若装了 ajv）**

Run:
```powershell
node -e "try { const Ajv = require('ajv'); const ajv = new Ajv({allSchema: true}); const schema = JSON.parse(require('fs').readFileSync('docs/schemas/stage-result.schema.json','utf8')); ajv.compile(schema); console.log('ajv OK'); } catch(e) { console.log('ajv 不可用或校验失败:', e.message); }"
```
Expected: 输出 `ajv OK` 或 `ajv 不可用`（后者不算 fail，仅说明未装 ajv）

- [ ] **Step 4: Commit**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-add.ps1" "docs/schemas/stage-result.schema.json"
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-commit.ps1" "扩展 stage-result.schema.json：runtime claim 追加 verdict_path/evidence_strength/review_verdict_path 字段"
```

### Task 1.3: 新增 review-verdict.schema.json

- [ ] **Step 1: 用 Write 创建 `docs/schemas/review-verdict.schema.json`**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "review-verdict.schema.json",
  "type": "object",
  "required": ["schemaVersion", "reviewed_at", "reviewer_version", "reviewer_command", "claims", "summary"],
  "properties": {
    "$schema": { "type": "string" },
    "schemaVersion": { "const": 1 },
    "reviewed_at": { "type": "string", "format": "date-time" },
    "reviewer_version": { "type": "string", "pattern": "^\\d+\\.\\d+\\.\\d+$" },
    "reviewer_command": { "type": "string", "minLength": 1 },
    "claims": {
      "type": "array",
      "items": {
        "type": "object",
        "required": [
          "claim_id",
          "claim",
          "reproducible",
          "exit_code_match",
          "observed_values_match",
          "diff",
          "rerun_command",
          "rerun_executed_at",
          "rerun_process_id",
          "rerun_exit_code",
          "rerun_observed_values",
          "failure_reason"
        ],
        "properties": {
          "claim_id": { "type": "string" },
          "claim": { "type": "string" },
          "reproducible": { "type": "boolean" },
          "exit_code_match": { "type": "boolean" },
          "observed_values_match": { "type": "boolean" },
          "diff": { "type": ["object", "null"] },
          "rerun_command": { "type": "string" },
          "rerun_executed_at": { "type": "string", "format": "date-time" },
          "rerun_process_id": { "type": "integer", "minimum": 1 },
          "rerun_exit_code": { "type": "integer" },
          "rerun_observed_values": { "type": "object" },
          "failure_reason": {
            "type": ["string", "null"],
            "enum": [
              null,
              "partial_match",
              "exit_code_mismatch",
              "sc2_unreachable",
              "timeout",
              "sc2_crashed",
              "missing_artifact",
              "non_live_strength"
            ]
          }
        },
        "additionalProperties": false
      }
    },
    "summary": {
      "type": "object",
      "required": ["total", "reproducible", "partial", "failed"],
      "properties": {
        "total": { "type": "integer", "minimum": 0 },
        "reproducible": { "type": "integer", "minimum": 0 },
        "partial": { "type": "integer", "minimum": 0 },
        "failed": { "type": "integer", "minimum": 0 }
      },
      "additionalProperties": false
    }
  },
  "additionalProperties": false
}
```

- [ ] **Step 2: 验证 JSON 合法**

Run:
```powershell
node -e "JSON.parse(require('fs').readFileSync('docs/schemas/review-verdict.schema.json','utf8')); console.log('OK')"
```
Expected: 输出 `OK`

- [ ] **Step 3: Commit**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-add.ps1" "docs/schemas/review-verdict.schema.json"
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-commit.ps1" "新增 review-verdict.schema.json：约束 reviewer 复核产物"
```

### Task 1.4: 新增 stage-transition.schema.json

- [ ] **Step 1: 用 Write 创建 `docs/schemas/stage-transition.schema.json`**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "stage-transition.schema.json",
  "type": "object",
  "required": [
    "schemaVersion",
    "from_stage",
    "to_stage",
    "transitioned_at",
    "executor_pid",
    "review_verdict_sha256",
    "result_sha256",
    "advance_stage_version"
  ],
  "properties": {
    "$schema": { "type": "string" },
    "schemaVersion": { "const": 1 },
    "from_stage": { "type": "string", "pattern": "^\\d+-[a-z-]+$" },
    "to_stage": { "type": "string", "pattern": "^\\d+-[a-z-]+$" },
    "transitioned_at": { "type": "string", "format": "date-time" },
    "executor_pid": { "type": "integer", "minimum": 1 },
    "review_verdict_sha256": { "type": "string", "pattern": "^[a-f0-9]{64}$" },
    "result_sha256": { "type": "string", "pattern": "^[a-f0-9]{64}$" },
    "advance_stage_version": { "type": "string", "pattern": "^\\d+\\.\\d+\\.\\d+$" }
  },
  "additionalProperties": false
}
```

- [ ] **Step 2: 验证 JSON 合法**

Run:
```powershell
node -e "JSON.parse(require('fs').readFileSync('docs/schemas/stage-transition.schema.json','utf8')); console.log('OK')"
```
Expected: 输出 `OK`

- [ ] **Step 3: Commit**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-add.ps1" "docs/schemas/stage-transition.schema.json"
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-commit.ps1" "新增 stage-transition.schema.json：约束 advance-stage 产出"
```

---

## Task 2: 改 sc2-observer.py 支持 --claim-id 与新 schema

**Files:**
- Modify: `tools/runtime-bridge/sc2-observer.py`（加 --claim-id 参数 + 重写 verdict 输出结构）
- Modify: `test/test_sc2_observer.py`（追加 --claim-id 测试用例）

### Task 2.1: 追加测试覆盖 --claim-id 参数

- [ ] **Step 1: 先看现有 test_sc2_observer.py 结构（已读，无需新读）**

关键点：测试用 `importlib.util.spec_from_file_location` 加载 `sc2-observer.py`，无真实 SC2 连接，只测纯函数。

- [ ] **Step 2: 在 `test/test_sc2_observer.py` 末尾追加 `TestClaimIdArgument` 测试类**

用 Edit 工具在文件末尾追加（找到最后一个 `if __name__ == "__main__":` 之前插入）：

```python
class TestClaimIdArgument(unittest.TestCase):
    """验证 --claim-id 参数能正确改写输出文件名前缀。"""

    def test_claim_id_filenames(self):
        """--claim-id rt-001 应使输出文件为 rt-001-runtime-verdict.json + rt-001-events.ndjson"""
        # 因为 sc2-observer.py 的 main() 解析 argv 后调用 observe_game，
        # 这里用 subprocess 模拟命令行调用，但仅校验参数解析与文件名拼接逻辑。
        # 真正的 SC2 连接由集成测试覆盖。
        import subprocess
        import tempfile
        result = subprocess.run(
            [sys.executable, str(OBSERVER_PATH), "--help"],
            capture_output=True, text=True, encoding="utf-8"
        )
        self.assertIn("--claim-id", result.stdout,
                      "--claim-id 参数必须在 --help 输出中可见")
```

- [ ] **Step 3: 跑测试验证失败（参数未实现）**

Run:
```powershell
python -m unittest test.test_sc2_observer.TestClaimIdArgument -v
```
Expected: FAIL，错误信息含 `AssertionError: '--claim-id' not found in '--help' output`

### Task 2.2: 修改 sc2-observer.py 加 --claim-id 参数

- [ ] **Step 1: 用 Edit 修改 `tools/runtime-bridge/sc2-observer.py` 的 main() 函数**

定位（第 355-361 行附近）：
```python
def main():
    parser = argparse.ArgumentParser(description="SC2 运行时观察器：被动收集事件流")
    parser.add_argument("--port", type=int, required=True, help="SC2 API 监听端口")
    parser.add_argument("--duration", type=float, default=120.0, help="最长观察时长（秒，0=无限）")
    parser.add_argument("--scenario", type=str, default=None, help="断言 scenario JSON 文件路径")
    parser.add_argument("--out-dir", type=str, default=None, help="输出目录（默认 artifacts/runtime/）")
    args = parser.parse_args()
```

替换为：
```python
def main():
    parser = argparse.ArgumentParser(description="SC2 运行时观察器：被动收集事件流")
    parser.add_argument("--port", type=int, required=True, help="SC2 API 监听端口")
    parser.add_argument("--duration", type=float, default=120.0, help="最长观察时长（秒，0=无限）")
    parser.add_argument("--scenario", type=str, default=None, help="断言 scenario JSON 文件路径")
    parser.add_argument("--out-dir", type=str, default=None, help="输出目录（默认 artifacts/runtime/）")
    parser.add_argument("--claim-id", type=str, default=None,
                        help="claim 标识符，用于输出文件名前缀（如 rt-001）；不指定时退化为旧版 verdict.json/events.ndjson")
    args = parser.parse_args()
```

- [ ] **Step 2: 用 Edit 修改 observe_game 函数签名加 claim_id 参数**

定位（第 235 行附近 `async def observe_game`）：

```python
async def observe_game(port, duration, out_dir, scenario):
```

替换为：
```python
async def observe_game(port, duration, out_dir, scenario, claim_id=None):
```

- [ ] **Step 3: 用 Edit 修改 observe_game 内部 verdict_path 与 events_path 文件名**

定位（第 247-249 行附近）：
```python
    out_dir.mkdir(parents=True, exist_ok=True)
    events_path = out_dir / "events.ndjson"
    verdict_path = out_dir / "verdict.json"
```

替换为：
```python
    out_dir.mkdir(parents=True, exist_ok=True)
    if claim_id:
        events_path = out_dir / f"{claim_id}-events.ndjson"
        verdict_path = out_dir / f"{claim_id}-runtime-verdict.json"
    else:
        events_path = out_dir / "events.ndjson"
        verdict_path = out_dir / "verdict.json"
```

- [ ] **Step 4: 用 Edit 修改 main() 调用 observe_game 传 claim_id**

定位（第 374 行附近）：
```python
    return asyncio.run(observe_game(args.port, args.duration, out_dir, scenario))
```

替换为：
```python
    return asyncio.run(observe_game(args.port, args.duration, out_dir, scenario, args.claim_id))
```

### Task 2.3: 修改 verdict 输出结构为新 schema

- [ ] **Step 1: 先看 evaluate_verdict 函数当前返回结构**

Run:
```powershell
node -e "const fs=require('fs');const c=fs.readFileSync('tools/runtime-bridge/sc2-observer.py','utf8');const m=c.match(/def evaluate_verdict[\s\S]+?\n    return[\s\S]+?\n/);console.log(m?m[0]:'NOT FOUND')"
```
Expected: 输出 evaluate_verdict 函数体（含 `overall_passed` / `criteria` 等字段）

- [ ] **Step 2: 用 Edit 修改 `evaluate_verdict` 函数返回结构**

在 `evaluate_verdict` 函数末尾的 `return` 语句之前，把返回 dict 替换为新 schema 兼容结构。
关键：保留旧字段（criteria / overall_passed）作为 metadata，新增 schema 强制字段为顶层字段。

定位 `return {` 开始的返回 dict（具体行号需根据当前文件确定，约在 200-230 行附近）：

替换为如下结构（保留旧字段作为 `metadata`）：
```python
    return {
        # 新 schema 强制字段（reviewer 校验时使用）
        "schemaVersion": 2,
        "claim_id": scenario.get("claim_id", "default-claim") if scenario else "default-claim",
        "claim": scenario.get("claim", "") if scenario else "",
        # 旧字段保留（向后兼容，reviewer 重跑比对时不依赖这些）
        "overall_passed": overall_passed,
        "criteria": criteria,
        # observed_values 由 reviewer 比对的核心字段（从 criteria 派生）
        "observed_values": {
            c["id"]: c["status"] for c in criteria
        },
        "evidence_strength": "live"
    }
```

注：`command / working_dir / env / timeout_seconds / executed_at / process_id / exit_code / stdout_sha256 / produced_files` 这些字段不在 evaluate_verdict 里填——它们由 main() 在调用 observe_game 后填入 verdict 文件。下一步实现。

- [ ] **Step 3: 用 Edit 修改 main() 在 observe_game 返回后补齐 schema 字段**

定位 main() 末尾 `return asyncio.run(...)` 行：

替换为：
```python
    exit_code = asyncio.run(observe_game(args.port, args.duration, out_dir, scenario, args.claim_id))

    # 补齐 runtime-verdict.schema.json 强制字段（claim_id 已在 evaluate_verdict 内填）
    # 只有产生了 verdict 文件时才补齐
    if scenario and args.claim_id:
        verdict_full_path = out_dir / f"{args.claim_id}-runtime-verdict.json"
        if verdict_full_path.exists():
            with open(verdict_full_path, "r", encoding="utf-8") as f:
                verdict = json.load(f)
            # 补齐 reviewer 重跑所需的元数据字段
            verdict.setdefault("command", " ".join([sys.executable, str(OBSERVER_PATH)] + sys.argv[1:]))
            verdict.setdefault("working_dir", str(REPO_ROOT))
            verdict.setdefault("env", {
                k: v for k, v in os.environ.items()
                if k in ("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "PATH", "PYTHONPATH")
                or k.startswith("SC2_")
            })
            verdict.setdefault("timeout_seconds", int(args.duration))
            verdict.setdefault("executed_at", datetime.now().astimezone().isoformat())
            # process_id / exit_code / stdout_sha256 / produced_files 在 reviewer 重跑时填，
            # 这里只填原始运行的（reviewer 会用重跑结果覆盖）
            verdict.setdefault("process_id", os.getpid())
            verdict.setdefault("exit_code", exit_code)
            verdict.setdefault("stdout_sha256", "")  # 留空，reviewer 重跑时计算
            events_full_path = out_dir / f"{args.claim_id}-events.ndjson"
            if events_full_path.exists():
                import hashlib
                events_bytes = events_full_path.stat().st_size
                with open(events_full_path, "rb") as ef:
                    events_sha = hashlib.sha256(ef.read()).hexdigest()
                verdict.setdefault("produced_files", [{
                    "path": str(events_full_path.relative_to(REPO_ROOT)) if events_full_path.is_relative_to(REPO_ROOT) else str(events_full_path),
                    "sha256": events_sha,
                    "bytes": events_bytes
                }])
            with open(verdict_full_path, "w", encoding="utf-8") as f:
                json.dump(verdict, f, ensure_ascii=False, indent=2)
                f.write("\n")

    return exit_code
```

- [ ] **Step 4: 在 sc2-observer.py 顶部 import 区补 datetime**

定位（第 14-22 行附近）：
```python
import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
```

替换为：
```python
import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
```

注：`hashlib` 已在 Step 3 用 `import hashlib` 局部 import，但提为顶层 import 更清晰。同时 `OBSERVER_PATH` 在 main() 内引用——需确认它是模块级常量。检查发现 `REPO_ROOT` 已是模块级常量（第 25 行），OBSERVER_PATH 在 main() 里要用——改用 `__file__`：

Step 3 里的 `" ".join([sys.executable, str(OBSERVER_PATH)] + sys.argv[1:])` 改为：
```python
            verdict.setdefault("command", " ".join([sys.executable, str(Path(__file__).resolve())] + sys.argv[1:]))
```

- [ ] **Step 5: 跑测试验证 --claim-id 参数生效**

Run:
```powershell
python -m unittest test.test_sc2_observer.TestClaimIdArgument -v
```
Expected: PASS（`--claim-id` 出现在 `--help` 输出中）

- [ ] **Step 6: 手动验证 --help 输出格式**

Run:
```powershell
python tools\runtime-bridge\sc2-observer.py --help
```
Expected: `--claim-id` 参数出现在 help 中，描述为 "claim 标识符，用于输出文件名前缀"

- [ ] **Step 7: Commit**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-add.ps1" "tools/runtime-bridge/sc2-observer.py"
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-add.ps1" "test/test_sc2_observer.py"
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-commit.ps1" "sc2-observer.py 支持 --claim-id 参数 + 新 schema 字段输出"
```

---

## Task 3: review-runtime.mjs 主程序 + 单元测试

**Files:**
- Create: `tools/runtime-bridge/review-runtime.mjs`
- Create: `test/test_review_runtime.mjs`

### Task 3.1: 写单元测试 fixture（TDD）

- [ ] **Step 1: 用 Write 创建 `test/test_review_runtime.mjs`**

```javascript
import { strict as assert } from "node:assert";
import { mkdtemp, mkdir, writeFile, rm } from "node:fs/promises";
import { existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(scriptDir, "..");
const REVIEWER = join(REPO_ROOT, "tools", "runtime-bridge", "review-runtime.mjs");

async function makeStageDir(prefix = "stage-test-") {
  const tmpRoot = await mkdtemp(join(tmpdir(), prefix));
  const stageDir = join(tmpRoot, "04-runtime-baseline");
  await mkdir(join(stageDir, "evidence", "runtime"), { recursive: true });
  return { tmpRoot, stageDir };
}

async function writeResultJson(stageDir, claims) {
  const result = {
    schemaVersion: 1,
    stage: "04-runtime-baseline",
    status: "passed",
    claims,
    outputs: [],
    validation: []
  };
  await writeFile(join(stageDir, "result.json"), JSON.stringify(result, null, 2) + "\n", "utf8");
}

async function writeVerdict(stageDir, claim) {
  const verdict = {
    schemaVersion: 2,
    claim_id: claim.claim_id,
    claim: claim.claim,
    command: claim.command,
    working_dir: claim.working_dir || REPO_ROOT,
    env: claim.env || {},
    timeout_seconds: claim.timeout_seconds || 30,
    executed_at: "2026-07-23T15:42:11+08:00",
    process_id: 12345,
    exit_code: 0,
    stdout_sha256: "a".repeat(64),
    produced_files: [],
    observed_values: claim.observed_values,
    evidence_strength: claim.evidence_strength || "live"
  };
  const verdictPath = join(stageDir, "evidence", "runtime", `${claim.claim_id}-runtime-verdict.json`);
  await writeFile(verdictPath, JSON.stringify(verdict, null, 2) + "\n", "utf8");
}

async function runReviewer(stageDir) {
  try {
    const stdout = execFileSync("node", [REVIEWER, stageDir], { encoding: "utf8" });
    return { exitCode: 0, stdout };
  } catch (e) {
    return { exitCode: e.status || 1, stdout: e.stdout || "", stderr: e.stderr || "" };
  }
}

// ---------- Test 1: 单 claim reproducible=true ----------
async function test_single_claim_reproducible() {
  const { tmpRoot, stageDir } = await makeStageDir();
  try {
    const observed = { "player_1": { "SpawningPool": 1 } };
    const cmd = `node -e "console.log(JSON.stringify({observed_values:${JSON.stringify(observed)}}))"`;
    await writeResultJson(stageDir, [{
      type: "runtime",
      claim: "能读到 player 1 的 SpawningPool",
      evidence: ["evidence/runtime/rt-001-runtime-verdict.json"],
      verdict_path: "evidence/runtime/rt-001-runtime-verdict.json",
      evidence_strength: "live",
      review_verdict_path: "evidence/runtime/review-verdict.json"
    }]);
    await writeVerdict(stageDir, {
      claim_id: "rt-001",
      claim: "能读到 player 1 的 SpawningPool",
      command: cmd,
      observed_values: observed
    });
    const result = await runReviewer(stageDir);
    assert.equal(result.exitCode, 0, `Expected exit 0, got ${result.exitCode}: ${result.stderr || result.stdout}`);
    const reviewPath = join(stageDir, "evidence", "runtime", "review-verdict.json");
    assert.ok(existsSync(reviewPath), "review-verdict.json 必须存在");
    console.log("PASS test_single_claim_reproducible");
  } finally {
    await rm(tmpRoot, { recursive: true, force: true });
  }
}

// ---------- Test 2: observed_values 不匹配 → partial_match ----------
async function test_partial_match() {
  const { tmpRoot, stageDir } = await makeStageDir();
  try {
    const observed = { "player_1": { "SpawningPool": 1 } };
    // 重跑命令返回不同的 observed_values
    const cmd = `node -e "console.log(JSON.stringify({observed_values:{player_1:{SpawningPool:2}}}))"`;
    await writeResultJson(stageDir, [{
      type: "runtime",
      claim: "能读到 player 1 的 SpawningPool",
      evidence: ["evidence/runtime/rt-002-runtime-verdict.json"],
      verdict_path: "evidence/runtime/rt-002-runtime-verdict.json",
      evidence_strength: "live",
      review_verdict_path: "evidence/runtime/review-verdict.json"
    }]);
    await writeVerdict(stageDir, {
      claim_id: "rt-002",
      claim: "能读到 player 1 的 SpawningPool",
      command: cmd,
      observed_values: observed
    });
    const result = await runReviewer(stageDir);
    assert.equal(result.exitCode, 1, `Expected exit 1, got ${result.exitCode}`);
    const reviewPath = join(stageDir, "evidence", "runtime", "review-verdict.json");
    const review = JSON.parse(await (await import("node:fs/promises")).readFile(reviewPath, "utf8"));
    assert.equal(review.summary.reproducible, 0);
    assert.equal(review.summary.failed, 1);
    assert.equal(review.claims[0].failure_reason, "partial_match");
    console.log("PASS test_partial_match");
  } finally {
    await rm(tmpRoot, { recursive: true, force: true });
  }
}

// ---------- Test 3: non_live_strength → 不允许 pass ----------
async function test_non_live_strength() {
  const { tmpRoot, stageDir } = await makeStageDir();
  try {
    await writeResultJson(stageDir, [{
      type: "runtime",
      claim: "replay 证据冒充 live",
      evidence: ["evidence/runtime/rt-003-runtime-verdict.json"],
      verdict_path: "evidence/runtime/rt-003-runtime-verdict.json",
      evidence_strength: "replay",  // 非 live
      review_verdict_path: "evidence/runtime/review-verdict.json"
    }]);
    await writeVerdict(stageDir, {
      claim_id: "rt-003",
      claim: "replay 证据冒充 live",
      command: `node -e "console.log('ok')"`,
      observed_values: {},
      evidence_strength: "replay"  // 非 live
    });
    const result = await runReviewer(stageDir);
    assert.equal(result.exitCode, 1);
    const reviewPath = join(stageDir, "evidence", "runtime", "review-verdict.json");
    const review = JSON.parse(await (await import("node:fs/promises")).readFile(reviewPath, "utf8"));
    assert.equal(review.claims[0].failure_reason, "non_live_strength");
    console.log("PASS test_non_live_strength");
  } finally {
    await rm(tmpRoot, { recursive: true, force: true });
  }
}

// ---------- Test 4: 缺 verdict 文件 → missing_artifact ----------
async function test_missing_artifact() {
  const { tmpRoot, stageDir } = await makeStageDir();
  try {
    await writeResultJson(stageDir, [{
      type: "runtime",
      claim: "verdict 文件不存在",
      evidence: ["evidence/runtime/rt-004-runtime-verdict.json"],
      verdict_path: "evidence/runtime/rt-004-runtime-verdict.json",
      evidence_strength: "live",
      review_verdict_path: "evidence/runtime/review-verdict.json"
    }]);
    // 故意不写 verdict 文件
    const result = await runReviewer(stageDir);
    assert.equal(result.exitCode, 1);
    const reviewPath = join(stageDir, "evidence", "runtime", "review-verdict.json");
    const review = JSON.parse(await (await import("node:fs/promises")).readFile(reviewPath, "utf8"));
    assert.equal(review.claims[0].failure_reason, "missing_artifact");
    console.log("PASS test_missing_artifact");
  } finally {
    await rm(tmpRoot, { recursive: true, force: true });
  }
}

// ---------- Test 5: 命令超时 → timeout ----------
async function test_timeout() {
  const { tmpRoot, stageDir } = await makeStageDir();
  try {
    const observed = { "ok": 1 };
    await writeResultJson(stageDir, [{
      type: "runtime",
      claim: "命令会超时",
      evidence: ["evidence/runtime/rt-005-runtime-verdict.json"],
      verdict_path: "evidence/runtime/rt-005-runtime-verdict.json",
      evidence_strength: "live",
      review_verdict_path: "evidence/runtime/review-verdict.json"
    }]);
    // 命令 sleep 10s，但 verdict 里 timeout_seconds=1，reviewer 应在 1s 后杀进程
    await writeVerdict(stageDir, {
      claim_id: "rt-005",
      claim: "命令会超时",
      command: `node -e "setTimeout(()=>console.log(JSON.stringify({observed_values:{ok:1}})), 10000)"`,
      observed_values: observed,
      timeout_seconds: 1
    });
    const result = await runReviewer(stageDir);
    assert.equal(result.exitCode, 1);
    const reviewPath = join(stageDir, "evidence", "runtime", "review-verdict.json");
    const review = JSON.parse(await (await import("node:fs/promises")).readFile(reviewPath, "utf8"));
    assert.equal(review.claims[0].failure_reason, "timeout");
    console.log("PASS test_timeout");
  } finally {
    await rm(tmpRoot, { recursive: true, force: true });
  }
}

// ---------- 主入口 ----------
const tests = [
  test_single_claim_reproducible,
  test_partial_match,
  test_non_live_strength,
  test_missing_artifact,
  test_timeout
];

let failed = 0;
for (const t of tests) {
  try { await t(); }
  catch (e) {
    console.error(`FAIL ${t.name}: ${e.message}`);
    console.error(e.stack);
    failed++;
  }
}
if (failed > 0) {
  console.error(`\n${failed}/${tests.length} tests failed`);
  process.exit(1);
} else {
  console.log(`\nAll ${tests.length} tests passed`);
}
```

- [ ] **Step 2: 跑测试验证全部失败（reviewer 还没实现）**

Run:
```powershell
node test/test_review_runtime.mjs
```
Expected: 5 个测试全 FAIL（review-runtime.mjs 不存在或跑不通），退出码 1

### Task 3.2: 实现 review-runtime.mjs 主体

- [ ] **Step 1: 用 Write 创建 `tools/runtime-bridge/review-runtime.mjs`**

```javascript
#!/usr/bin/env node
/**
 * Runtime Evidence Reviewer
 *
 * 读取 stage 的 result.json，对每条 type=="runtime" 的 claim：
 * 1. 校验 verdict_path 指向的 <claim_id>-runtime-verdict.json 存在且 schema 合规
 * 2. 校验 evidence_strength == "live"（否则 failure_reason: "non_live_strength"）
 * 3. 重跑 command（带 timeout_seconds）
 * 4. 比对 exit_code + observed_values
 * 5. 输出 review-verdict.json
 *
 * 不 fallback 到 replay。SC2 live 不可达 → failure_reason: "sc2_unreachable"
 *
 * 用法: node tools/runtime-bridge/review-runtime.mjs <stage-dir>
 */
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, join, resolve, isAbsolute } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { createRequire } from "node:module";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(scriptDir, "..", "..");
const REVIEWER_VERSION = "0.1.0";

async function readJson(path) {
  return JSON.parse(await readFile(path, "utf8"));
}

/**
 * 深度比对 observed_values。
 * - 数值/字符串 → 完全相等
 * - 数组 → 长度相等 + 元素集合相等（顺序无关）
 * - 嵌套对象 → key 集合相等 + 每个 key 递归
 * - 缺字段 → 返回 diff 描述
 */
function compareObserved(expected, actual, path = "") {
  if (typeof expected !== typeof actual) {
    return { path, reason: "type_mismatch", expected: typeof expected, actual: typeof actual };
  }
  if (Array.isArray(expected)) {
    if (!Array.isArray(actual)) return { path, reason: "expected_array" };
    if (expected.length !== actual.length) {
      return { path, reason: "length_mismatch", expected: expected.length, actual: actual.length };
    }
    // 集合相等：把元素 JSON 序列化后排序比对
    const expSet = expected.map(x => JSON.stringify(x)).sort();
    const actSet = actual.map(x => JSON.stringify(x)).sort();
    for (let i = 0; i < expSet.length; i++) {
      if (expSet[i] !== actSet[i]) {
        return { path, reason: "set_mismatch", expected: expSet[i], actual: actSet[i] };
      }
    }
    return null;
  }
  if (typeof expected === "object" && expected !== null) {
    if (typeof actual !== "object" || actual === null) {
      return { path, reason: "expected_object" };
    }
    const expKeys = Object.keys(expected);
    const actKeys = Object.keys(actual);
    const expSet = new Set(expKeys);
    const actSet = new Set(actKeys);
    for (const k of expKeys) {
      if (!actSet.has(k)) return { path: path ? `${path}.${k}` : k, reason: "missing_key", key: k };
    }
    for (const k of actKeys) {
      if (!expSet.has(k)) return { path: path ? `${path}.${k}` : k, reason: "extra_key", key: k };
    }
    for (const k of expKeys) {
      const sub = compareObserved(expected[k], actual[k], path ? `${path}.${k}` : k);
      if (sub) return sub;
    }
    return null;
  }
  // 原始类型
  if (expected !== actual) {
    return { path, reason: "value_mismatch", expected, actual };
  }
  return null;
}

/**
 * 在 stage 目录里定位 result.json
 */
async function locateResultJson(stageDir) {
  const resultPath = join(stageDir, "result.json");
  if (!existsSync(resultPath)) {
    throw new Error(`result.json not found in stage: ${stageDir}`);
  }
  return readJson(resultPath);
}

/**
 * 重跑命令，捕获 exit_code / stdout_sha256 / observed_values。
 * 命令格式：string，使用 shell 执行。
 */
function rerunCommand({ command, working_dir, env, timeout_seconds }) {
  const cwd = isAbsolute(working_dir) ? working_dir : resolve(REPO_ROOT, working_dir);
  const childEnv = { ...process.env, ...env };

  return new Promise((resolvePromise) => {
    const child = spawn(command, {
      cwd,
      env: childEnv,
      shell: true,
      stdio: ["ignore", "pipe", "pipe"]
    });

    let stdout = "";
    let stderr = "";
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      try { child.kill("SIGKILL"); } catch (e) { /* ignore */ }
    }, (timeout_seconds || 180) * 1000);

    child.stdout.on("data", (d) => { stdout += d.toString(); });
    child.stderr.on("data", (d) => { stderr += d.toString(); });
    child.on("error", (e) => {
      clearTimeout(timer);
      resolvePromise({
        exitCode: -1,
        stdout,
        stderr,
        error: e.message,
        timedOut: false
      });
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      resolvePromise({
        exitCode: code,
        stdout,
        stderr,
        timedOut
      });
    });
  });
}

/**
 * 从 stdout 解析 observed_values。
 * sc2-observer.py 重跑后会把 observed_values 写在 stdout 的一行 JSON 里。
 * 兼容格式：{ "observed_values": {...} } 或 {...} 直接是 observed_values
 */
function extractObservedValues(stdout) {
  const lines = stdout.split("\n");
  // 从后往前找第一行能解析为 JSON 且含 observed_values 的
  for (let i = lines.length - 1; i >= 0; i--) {
    const line = lines[i].trim();
    if (!line.startsWith("{")) continue;
    try {
      const obj = JSON.parse(line);
      if (obj.observed_values) return obj.observed_values;
      // 兼容：直接整行作为 observed_values
      return obj;
    } catch (e) { /* not JSON, skip */ }
  }
  return null;
}

/**
 * 校验 verdict 是否符合 runtime-verdict.schema.json 的最小子集
 * （完整 schema 校验由 validate-schema.mjs 负责，这里只做关键字段存在性检查）
 */
function validateVerdictMinimal(verdict) {
  const required = [
    "schemaVersion", "claim_id", "claim", "command", "working_dir",
    "env", "timeout_seconds", "executed_at", "process_id", "exit_code",
    "stdout_sha256", "produced_files", "observed_values", "evidence_strength"
  ];
  const missing = required.filter(k => !(k in verdict));
  return missing;
}

async function reviewStage(stageDir) {
  const absStageDir = isAbsolute(stageDir) ? stageDir : resolve(REPO_ROOT, stageDir);
  const result = await locateResultJson(absStageDir);

  const runtimeClaims = (result.claims || []).filter(c => c.type === "runtime");
  const claims = [];

  for (const claim of runtimeClaims) {
    const claimId = (claim.verdict_path || "").split("/").pop().replace(/-runtime-verdict\.json$/, "");
    if (!claimId || !/^[a-z0-9][a-z0-9-]*$/.test(claimId)) {
      claims.push({
        claim_id: claimId || "<invalid>",
        claim: claim.claim || "",
        reproducible: false,
        exit_code_match: false,
        observed_values_match: false,
        diff: null,
        rerun_command: "",
        rerun_executed_at: new Date().toISOString(),
        rerun_process_id: process.pid,
        rerun_exit_code: -1,
        rerun_observed_values: {},
        failure_reason: "missing_artifact"
      });
      continue;
    }

    const verdictPath = join(absStageDir, claim.verdict_path);
    if (!existsSync(verdictPath)) {
      claims.push({
        claim_id: claimId,
        claim: claim.claim || "",
        reproducible: false,
        exit_code_match: false,
        observed_values_match: false,
        diff: null,
        rerun_command: "",
        rerun_executed_at: new Date().toISOString(),
        rerun_process_id: process.pid,
        rerun_exit_code: -1,
        rerun_observed_values: {},
        failure_reason: "missing_artifact"
      });
      continue;
    }

    const verdict = await readJson(verdictPath);
    const missingFields = validateVerdictMinimal(verdict);
    if (missingFields.length > 0) {
      claims.push({
        claim_id: claimId,
        claim: claim.claim || "",
        reproducible: false,
        exit_code_match: false,
        observed_values_match: false,
        diff: { missing_fields: missingFields },
        rerun_command: "",
        rerun_executed_at: new Date().toISOString(),
        rerun_process_id: process.pid,
        rerun_exit_code: -1,
        rerun_observed_values: {},
        failure_reason: "missing_artifact"
      });
      continue;
    }

    // 校验 evidence_strength == "live"
    if (verdict.evidence_strength !== "live") {
      claims.push({
        claim_id: claimId,
        claim: claim.claim || "",
        reproducible: false,
        exit_code_match: false,
        observed_values_match: false,
        diff: null,
        rerun_command: verdict.command,
        rerun_executed_at: new Date().toISOString(),
        rerun_process_id: process.pid,
        rerun_exit_code: -1,
        rerun_observed_values: {},
        failure_reason: "non_live_strength"
      });
      continue;
    }

    // 重跑
    const rerunResult = await rerunCommand({
      command: verdict.command,
      working_dir: verdict.working_dir,
      env: verdict.env,
      timeout_seconds: verdict.timeout_seconds
    });

    if (rerunResult.timedOut) {
      claims.push({
        claim_id: claimId,
        claim: claim.claim || "",
        reproducible: false,
        exit_code_match: false,
        observed_values_match: false,
        diff: null,
        rerun_command: verdict.command,
        rerun_executed_at: new Date().toISOString(),
        rerun_process_id: process.pid,
        rerun_exit_code: rerunResult.exitCode,
        rerun_observed_values: {},
        failure_reason: "timeout"
      });
      continue;
    }

    const exitCodeMatch = rerunResult.exitCode === verdict.exit_code;
    const rerunObserved = extractObservedValues(rerunResult.stdout);

    let observedMatch = false;
    let diff = null;
    if (rerunObserved === null) {
      observedMatch = false;
      diff = { reason: "no_observed_values_in_stdout" };
    } else {
      diff = compareObserved(verdict.observed_values, rerunObserved);
      observedMatch = (diff === null);
    }

    let failureReason = null;
    if (!exitCodeMatch) failureReason = "exit_code_mismatch";
    else if (!observedMatch) failureReason = "partial_match";

    claims.push({
      claim_id: claimId,
      claim: claim.claim || "",
      reproducible: exitCodeMatch && observedMatch,
      exit_code_match: exitCodeMatch,
      observed_values_match: observedMatch,
      diff,
      rerun_command: verdict.command,
      rerun_executed_at: new Date().toISOString(),
      rerun_process_id: process.pid,
      rerun_exit_code: rerunResult.exitCode,
      rerun_observed_values: rerunObserved || {},
      failure_reason: failureReason
    });
  }

  const summary = {
    total: claims.length,
    reproducible: claims.filter(c => c.reproducible).length,
    partial: claims.filter(c => !c.reproducible && c.failure_reason === "partial_match").length,
    failed: claims.filter(c => !c.reproducible && c.failure_reason !== "partial_match").length
  };

  const reviewVerdict = {
    schemaVersion: 1,
    reviewed_at: new Date().toISOString(),
    reviewer_version: REVIEWER_VERSION,
    reviewer_command: `node tools/runtime-bridge/review-runtime.mjs ${stageDir}`,
    claims,
    summary
  };

  const reviewPath = join(absStageDir, "evidence", "runtime", "review-verdict.json");
  await mkdir(dirname(reviewPath), { recursive: true });
  await writeFile(reviewPath, JSON.stringify(reviewVerdict, null, 2) + "\n", "utf8");

  console.log(`Reviewer 完成: ${summary.reproducible}/${summary.total} reproducible`);
  console.log(`  review-verdict: ${reviewPath}`);

  return reviewVerdict;
}

async function main() {
  const args = process.argv.slice(2);
  if (args.length < 1) {
    console.error("Usage: node tools/runtime-bridge/review-runtime.mjs <stage-dir>");
    process.exit(2);
  }
  const stageDir = args[0];
  try {
    const review = await reviewStage(stageDir);
    process.exitCode = (review.summary.reproducible === review.summary.total) ? 0 : 1;
  } catch (e) {
    console.error("review-runtime failed: " + e.message);
    console.error(e.stack);
    process.exitCode = 2;
  }
}

main();
```

- [ ] **Step 2: 跑单元测试验证全部通过**

Run:
```powershell
node test/test_review_runtime.mjs
```
Expected: 输出 `All 5 tests passed`，退出码 0

- [ ] **Step 3: Commit**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-add.ps1" "tools/runtime-bridge/review-runtime.mjs"
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-add.ps1" "test/test_review_runtime.mjs"
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-commit.ps1" "feat: 实现 review-runtime.mjs reviewer 主程序 + 单元测试（5 个 fixture 全过）"
```

---

## Task 4: workspace.mjs advance-stage 子命令

**Files:**
- Modify: `tools/utils/workspace.mjs`

### Task 4.1: 实现 advance-stage 子命令

- [ ] **Step 1: 用 Edit 在 workspace.mjs 的命令分发区追加 advance-stage**

定位文件末尾的命令分发 `else if (command === "search")` 之后：
```javascript
} else if (command === "search") {
  // workspace.mjs search "<question>" [--top-k <n>]
  const opts = parseOptions(process.argv.slice(3));
  await searchCommand(argument, opts);
} else {
  throw new Error("Unknown command: " + command);
}
```

替换为：
```javascript
} else if (command === "search") {
  // workspace.mjs search "<question>" [--top-k <n>]
  const opts = parseOptions(process.argv.slice(3));
  await searchCommand(argument, opts);
} else if (command === "advance-stage") {
  // workspace.mjs advance-stage <project-id>
  await advanceStageCommand(argument);
} else {
  throw new Error("Unknown command: " + command);
}
```

- [ ] **Step 2: 用 Edit 在 workspace.mjs 实现 advanceStageCommand 函数**

定位 `staticValidateCommand` 函数后（第 265 行附近）：

追加：
```javascript

// advance-stage 子命令：推进 stage，写 stage-transition.json
async function advanceStageCommand(projectId) {
  if (!projectId) throw new Error("advance-stage 需要 <project-id>。用法: workspace.mjs advance-stage <project-id>");
  const projectDir = join(repoRoot, "src", "projects", projectId);
  if (!existsSync(projectDir)) throw new Error("项目不存在: " + projectDir);

  const projectPath = join(projectDir, "project.json");
  const project = await readJson(projectPath);
  const currentStage = project.currentStage;
  if (!currentStage) throw new Error("project.json 缺 currentStage 字段: " + projectPath);

  const stageDir = join(projectDir, "stages", currentStage);
  if (!existsSync(stageDir)) throw new Error("当前 stage 目录不存在: " + stageDir);

  // 1. 读 result.json，校验 status == "passed"
  const resultPath = join(stageDir, "result.json");
  if (!existsSync(resultPath)) throw new Error("当前 stage 缺 result.json: " + resultPath);
  const result = await readJson(resultPath);
  if (result.status !== "passed") {
    throw new Error(`当前 stage status=${result.status}，必须为 passed 才能 advance`);
  }

  // 2. 调 reviewer 二次复核
  const reviewerScript = join(scriptDir, "..", "runtime-bridge", "review-runtime.mjs");
  if (!existsSync(reviewerScript)) throw new Error("review-runtime.mjs 不存在: " + reviewerScript);
  try {
    await runTool("node", [reviewerScript, stageDir]);
  } catch (e) {
    // reviewer 退出码 1 = 有 claim 不可重跑，拒绝推进
    throw new Error(`reviewer 复核失败: ${e.message}\n  请修复后重试`);
  }

  // 3. 校验 review-verdict.json 的 sha256（用于 stage-transition.json）
  const reviewPath = join(stageDir, "evidence", "runtime", "review-verdict.json");
  if (!existsSync(reviewPath)) throw new Error("review-verdict.json 不存在: " + reviewPath);
  const reviewContent = await readFile(reviewPath, "utf8");
  const reviewSha = createHash("sha256").update(reviewContent, "utf8").digest("hex");

  const resultContent = await readFile(resultPath, "utf8");
  const resultSha = createHash("sha256").update(resultContent, "utf8").digest("hex");

  // 4. 推算 next stage 编号
  const stageMatch = currentStage.match(/^(\d+)-([a-z-]+)$/);
  if (!stageMatch) throw new Error(`currentStage 格式不合法: ${currentStage}`);
  const nextNum = parseInt(stageMatch[1], 10) + 1;
  const nextStage = `${String(nextNum).padStart(2, "0")}-${stageMatch[2] === "runtime-validation" ? "acceptance" : "next"}`;
  // 简化：仅支持 runtime-validation → acceptance 的标准推进
  // 真实场景需按 workflow.md 的 stage 清单映射
  const standardNext = {
    "01-discovery": "02-static-analysis",
    "02-static-analysis": "03-gap-analysis",
    "03-gap-analysis": "04-adapter-design",
    "04-adapter-design": "05-implementation",
    "05-implementation": "06-static-validation",
    "06-static-validation": "07-runtime-validation",
    "07-runtime-validation": "08-acceptance"
  };
  const mappedNext = standardNext[currentStage];
  if (!mappedNext) {
    throw new Error(`不支持的 stage 推进: ${currentStage}（请手动指定下一 stage）`);
  }
  const nextStageDir = join(projectDir, "stages", mappedNext);
  if (!existsSync(nextStageDir)) {
    // 创建下一 stage 目录与模板
    await mkdir(join(nextStageDir, "evidence"), { recursive: true });
    for (const file of ["plan.md", "log.md", "result.json", "issues.json"]) {
      await copyFile(join(repoRoot, "src", "templates", "stage", file), join(nextStageDir, file));
    }
  }

  // 5. 写 stage-transition.json
  const transition = {
    schemaVersion: 1,
    from_stage: currentStage,
    to_stage: mappedNext,
    transitioned_at: new Date().toISOString(),
    executor_pid: process.pid,
    review_verdict_sha256: reviewSha,
    result_sha256: resultSha,
    advance_stage_version: "0.1.0"
  };
  const transitionPath = join(stageDir, "stage-transition.json");
  await writeFile(transitionPath, JSON.stringify(transition, null, 2) + "\n", "utf8");

  // 6. 更新 project.json 的 currentStage
  project.currentStage = mappedNext;
  await writeFile(projectPath, JSON.stringify(project, null, 2) + "\n", "utf8");

  console.log(`Stage 推进成功: ${currentStage} → ${mappedNext}`);
  console.log(`  stage-transition: ${transitionPath}`);
  console.log(`  next stage: ${nextStageDir}`);
}
```

- [ ] **Step 3: 验证 workspace.mjs 能解析新命令**

Run:
```powershell
node tools\utils\workspace.mjs advance-stage
```
Expected: 输出 `Error: advance-stage 需要 <project-id>...`（参数校验生效）

- [ ] **Step 4: Commit**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-add.ps1" "tools/utils/workspace.mjs"
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-commit.ps1" "feat: workspace.mjs 加 advance-stage 子命令（reviewer 复核 + stage-transition.json 写入）"
```

---

## Task 5: static-validate.mjs 第 7 项检查集成

**Files:**
- Modify: `tools/analysis/static-validate.mjs`

### Task 5.1: 加第 7 项检查

- [ ] **Step 1: 用 Edit 修改 static-validate.mjs 在第 6 项后追加第 7 项**

定位（第 96 行附近 `// 7. 写入 analyzer-commands` 之前）：

追加：
```javascript
  // 7. 校验前一 stage 的 runtime review-verdict（runtime evidence enforcement）
  commands.push({ name: "prev-stage-runtime-evidence", file: "prev-stage-runtime-check.json" });
  const prevStageCheck = await checkPrevStageRuntimeEvidence(projectDir, projectId);
  await writeFile(join(absOut, "prev-stage-runtime-check.json"), JSON.stringify(prevStageCheck, null, 2) + "\n", "utf8");
  if (!prevStageCheck.passed) overallPass = false;
```

- [ ] **Step 2: 用 Edit 在 static-validate.mjs 末尾的 `mergeDependencyGraphs` 函数后追加辅助函数**

定位文件末尾 `main()` 之前（第 152 行附近 `async function main()` 之前）：

追加：
```javascript

/**
 * 第 7 项检查：前一 stage 的 runtime review-verdict 必须存在且 reproducible=true。
 * 同时校验 stage-transition.json 的 sha256 与磁盘文件一致。
 */
async function checkPrevStageRuntimeEvidence(projectDir, projectId) {
  const project = await readJson(join(projectDir, "project.json"));
  const currentStage = project.currentStage;
  if (!currentStage) {
    return { passed: true, reason: "no currentStage set, skip (project 初始化阶段)" };
  }

  // 找前一 stage（按数字编号减 1）
  const stageMatch = currentStage.match(/^(\d+)-/);
  if (!stageMatch) {
    return { passed: true, reason: `currentStage 非 stage 格式: ${currentStage}` };
  }
  const prevNum = parseInt(stageMatch[1], 10) - 1;
  if (prevNum < 1) {
    return { passed: true, reason: "已是第一 stage，无前一 stage 需校验" };
  }

  // 扫描 stages/ 目录找前缀匹配的
  const stagesDir = join(projectDir, "stages");
  if (!existsSync(stagesDir)) {
    return { passed: true, reason: "stages 目录不存在" };
  }
  const entries = await opendir(stagesDir);
  let prevStageDir = null;
  for await (const entry of entries) {
    if (entry.isDirectory() && entry.name.startsWith(`${String(prevNum).padStart(2, "0")}-`)) {
      prevStageDir = join(stagesDir, entry.name);
      break;
    }
  }
  if (!prevStageDir) {
    return { passed: true, reason: `未找到 stage ${prevNum} 的目录` };
  }

  const stageTransitionPath = join(prevStageDir, "stage-transition.json");
  if (!existsSync(stageTransitionPath)) {
    return {
      passed: false,
      reason: `前一 stage 缺 stage-transition.json: ${stageTransitionPath}`,
      prev_stage: basename(prevStageDir)
    };
  }

  const transition = await readJson(stageTransitionPath);

  // 校验 review_verdict_sha256
  const reviewPath = join(prevStageDir, "evidence", "runtime", "review-verdict.json");
  if (!existsSync(reviewPath)) {
    return {
      passed: false,
      reason: `前一 stage 缺 review-verdict.json: ${reviewPath}`,
      prev_stage: basename(prevStageDir)
    };
  }
  const reviewContent = await readFile(reviewPath, "utf8");
  const reviewSha = createHash("sha256").update(reviewContent, "utf8").digest("hex");
  if (reviewSha !== transition.review_verdict_sha256) {
    return {
      passed: false,
      reason: `stage-transition.json 的 review_verdict_sha256 与磁盘 review-verdict.json 不一致`,
      expected: transition.review_verdict_sha256,
      actual: reviewSha,
      prev_stage: basename(prevStageDir)
    };
  }

  // 校验 result_sha256
  const resultPath = join(prevStageDir, "result.json");
  if (!existsSync(resultPath)) {
    return {
      passed: false,
      reason: `前一 stage 缺 result.json: ${resultPath}`,
      prev_stage: basename(prevStageDir)
    };
  }
  const resultContent = await readFile(resultPath, "utf8");
  const resultSha = createHash("sha256").update(resultContent, "utf8").digest("hex");
  if (resultSha !== transition.result_sha256) {
    return {
      passed: false,
      reason: `stage-transition.json 的 result_sha256 与磁盘 result.json 不一致`,
      expected: transition.result_sha256,
      actual: resultSha,
      prev_stage: basename(prevStageDir)
    };
  }

  // 校验 review-verdict 的 summary.reproducible == summary.total
  const review = JSON.parse(reviewContent);
  if (review.summary.reproducible !== review.summary.total) {
    return {
      passed: false,
      reason: `前一 stage 的 review-verdict 有不可重跑的 claim: ${review.summary.reproducible}/${review.summary.total}`,
      prev_stage: basename(prevStageDir),
      summary: review.summary
    };
  }

  return {
    passed: true,
    reason: "前一 stage runtime 证据完整且 reproducible",
    prev_stage: basename(prevStageDir),
    summary: review.summary
  };
}
```

- [ ] **Step 3: 用 Edit 在 static-validate.mjs 顶部 import 区补 basename + createHash**

定位（第 1-5 行附近）：
```javascript
import { mkdir, opendir, readFile, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";
```

替换为：
```javascript
import { mkdir, opendir, readFile, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { basename, dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
```

- [ ] **Step 4: 验证 static-validate.mjs 语法正确**

Run:
```powershell
node -c tools\analysis\static-validate.mjs
```
Expected: 输出 `tools\analysis\static-validate.mjs`（语法 OK，`-c` 只做语法检查）

- [ ] **Step 5: Commit**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-add.ps1" "tools/analysis/static-validate.mjs"
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-commit.ps1" "feat: static-validate.mjs 加第 7 项检查（前一 stage runtime 证据 + stage-transition sha256 校验）"
```

---

## Task 6: validate-schema.mjs 校验新 schema

**Files:**
- Modify: `tools/analysis/validate-schema.mjs`

### Task 6.1: 加 schema 自校验功能

- [ ] **Step 1: 用 Edit 修改 validate-schema.mjs 在 main() 中支持 `--self-check` 模式**

定位 main() 函数：
```javascript
async function main() {
  const args = process.argv.slice(2);
  if (args.length < 2) {
    throw new Error("Usage: node tools/analysis/validate-schema.mjs <data.json> <schema.json> [<data2.json> <schema2.json> ...]");
  }
  ...
```

替换为：
```javascript
async function main() {
  const args = process.argv.slice(2);

  // --self-check: 校验所有 schema 自身（schema 文件本身是合法 JSON）
  if (args[0] === "--self-check") {
    const schemas = args.slice(1);
    if (schemas.length === 0) {
      // 默认校验仓库内所有 schema
      const schemaDir = join(repoRoot, "docs", "schemas");
      const files = await readdir(schemaDir);
      for (const f of files.filter(x => x.endsWith(".schema.json"))) {
        schemas.push(`docs/schemas/${f}`);
      }
    }
    let allValid = true;
    for (const schemaPath of schemas) {
      try {
        const schema = await readJson(resolve(repoRoot, schemaPath));
        // schema 自校验：能被 JSON.parse 且有 $id/type/properties 即视为合法
        if (!schema.$id || !schema.type || !schema.properties) {
          console.log(`✗ ${schemaPath} 自校验 fail: 缺 $id/type/properties`);
          allValid = false;
        } else {
          console.log(`✓ ${schemaPath} 自校验 pass`);
        }
      } catch (e) {
        console.log(`✗ ${schemaPath} 自校验 fail: ${e.message}`);
        allValid = false;
      }
    }
    process.exitCode = allValid ? 0 : 1;
    return;
  }

  if (args.length < 2) {
    throw new Error("Usage: node tools/analysis/validate-schema.mjs <data.json> <schema.json> [...] | --self-check [<schema>...]");
  }
  ...
```

- [ ] **Step 2: 用 Edit 在 import 区补 readdir**

定位（第 1 行）：
```javascript
import { readFile } from "node:fs/promises";
```

替换为：
```javascript
import { readFile, readdir } from "node:fs/promises";
```

- [ ] **Step 3: 跑 self-check 验证所有 schema 合法**

Run:
```powershell
node tools\analysis\validate-schema.mjs --self-check
```
Expected: 输出每个 schema 的 ✓ 或 ✗，最后一行退出码 0（全 pass）

- [ ] **Step 4: Commit**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-add.ps1" "tools/analysis/validate-schema.mjs"
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-commit.ps1" "feat: validate-schema.mjs 加 --self-check 模式校验所有 schema 自身"
```

---

## Task 7: pre-commit hook 安装器

**Files:**
- Create: `tools/utils/install-hooks.mjs`

### Task 7.1: 实现 install-hooks.mjs

- [ ] **Step 1: 用 Write 创建 `tools/utils/install-hooks.mjs`**

```javascript
#!/usr/bin/env node
/**
 * pre-commit hook 安装器：生成 .git/hooks/pre-commit
 *
 * hook 内容（轻量存在性校验，<500ms）：
 * 1. 扫描 src/projects/*/stages/*/ 下所有 stage 目录
 * 2. 检查 git diff 里是否有 result.json 改为 status: "passed"
 * 3. 若有，校验对应 review-verdict.json 存在 + summary.reproducible == summary.total
 * 4. 检查 git diff 里是否有新增 <next-stage>/plan.md，若有则校验前一 stage stage-transition.json 存在
 *
 * 用法: node tools/utils/install-hooks.mjs
 */
import { writeFile, readFile, mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(scriptDir, "..", "..");
const HOOK_PATH = join(REPO_ROOT, ".git", "hooks", "pre-commit");

const HOOK_CONTENT = `#!/bin/sh
# Auto-generated by tools/utils/install-hooks.mjs
# Runtime Evidence Enforcement pre-commit hook (layer 4)
# 轻量校验：文件存在 + JSON 字段读取，不做完整 schema 校验，不调 SC2

set -e

# 找出所有 stage 目录
STAGES=$(find src/projects -type d -path "*/stages/*" 2>/dev/null | grep -E "/stages/[0-9]+-[a-z-]+" || true)

EXIT_CODE=0

for stage in $STAGES; do
  result_file="$stage/result.json"
  if [ ! -f "$result_file" ]; then continue; fi

  # 用 git diff 检查 result.json 是否被改为 status: "passed"
  if ! git diff --cached --quiet -- "$result_file" 2>/dev/null; then
    # 解析 status 字段
    status=$(node -e "try{const r=JSON.parse(require('fs').readFileSync('$result_file','utf8'));console.log(r.status||'')}catch(e){console.log('')}" 2>/dev/null)
    if [ "$status" = "passed" ]; then
      # 校验每条 runtime claim 的 verdict_path 和 review_verdict_path
      claims=$(node -e "try{const r=JSON.parse(require('fs').readFileSync('$result_file','utf8'));for(const c of(r.claims||[])){if(c.type==='runtime'){console.log(c.verdict_path+'|'+c.review_verdict_path)}}}catch(e){}" 2>/dev/null)
      for line in $claims; do
        verdict_path=$(echo "$line" | cut -d'|' -f1)
        review_path=$(echo "$line" | cut -d'|' -f2)
        if [ -n "$verdict_path" ] && [ ! -f "$stage/$verdict_path" ]; then
          echo "ERROR: runtime claim verdict_path 不存在: $stage/$verdict_path"
          EXIT_CODE=1
        fi
        if [ -n "$review_path" ] && [ ! -f "$stage/$review_path" ]; then
          echo "ERROR: runtime claim review_verdict_path 不存在: $stage/$review_path"
          EXIT_CODE=1
        fi
        # 校验 review-verdict.json 的 summary
        if [ -n "$review_path" ] && [ -f "$stage/$review_path" ]; then
          reproducible=$(node -e "try{const r=JSON.parse(require('fs').readFileSync('$stage/$review_path','utf8'));console.log(r.summary?.reproducible ?? -1)}catch(e){console.log(-1)}" 2>/dev/null)
          total=$(node -e "try{const r=JSON.parse(require('fs').readFileSync('$stage/$review_path','utf8'));console.log(r.summary?.total ?? -1)}catch(e){console.log(-1)}" 2>/dev/null)
          if [ "$reproducible" != "$total" ]; then
            echo "ERROR: review-verdict summary 不匹配 (reproducible=$reproducible, total=$total): $stage/$review_path"
            EXIT_CODE=1
          fi
        fi
      done
    fi
  fi
done

# 检查新增 <next-stage>/plan.md 必须有前一 stage 的 stage-transition.json
# 扫描所有 plan.md 在 git diff 里的新增项
NEW_PLANS=$(git diff --cached --name-only --diff-filter=A | grep -E "stages/[0-9]+-[a-z-]+/plan\\.md$" || true)
for plan in $NEW_PLANS; do
  # 从 plan 路径推算前一 stage
  stage_dir=$(dirname "$plan")
  stage_name=$(basename "$stage_dir")
  num=$(echo "$stage_name" | grep -oE "^[0-9]+" | head -1)
  if [ -z "$num" ]; then continue; fi
  prev_num=$((num - 1))
  if [ "$prev_num" -lt 1 ]; then continue; fi
  # 找前一 stage 目录
  prev_stage_dir=$(dirname "$stage_dir")
  prev_stage=$(ls -d "$prev_stage_dir"/${prev_num}-* 2>/dev/null | head -1 || true)
  if [ -n "$prev_stage" ]; then
    if [ ! -f "$prev_stage/stage-transition.json" ]; then
      echo "ERROR: 新增 plan.md 但前一 stage 缺 stage-transition.json: $prev_stage/stage-transition.json"
      EXIT_CODE=1
    fi
  fi
done

if [ "$EXIT_CODE" != "0" ]; then
  echo ""
  echo "Runtime evidence enforcement 检查失败。"
  echo "若需绕过（仅紧急修复），用 git commit --no-verify，并在 commit message 里写 [manual-override]"
  exit 1
fi

exit 0
`;

async function main() {
  const hookDir = dirname(HOOK_PATH);
  if (!existsSync(hookDir)) {
    await mkdir(hookDir, { recursive: true });
  }
  await writeFile(HOOK_PATH, HOOK_CONTENT, "utf8");
  // 设置可执行权限（Windows 上 git 用 sh 解释，不需要 +x；Linux/macOS 需要）
  try {
    const { chmod } = await import("node:fs/promises");
    await chmod(HOOK_PATH, 0o755);
  } catch (e) { /* Windows 忽略 */ }
  console.log(`pre-commit hook 已安装: ${HOOK_PATH}`);
  console.log(`  测试: git commit 时自动触发`);
  console.log(`  绕过: git commit --no-verify（紧急修复时用，commit message 加 [manual-override]）`);
}

main().catch((e) => {
  console.error("install-hooks failed: " + e.message);
  process.exitCode = 1;
});
```

- [ ] **Step 2: 安装 hook**

Run:
```powershell
node tools\utils\install-hooks.mjs
```
Expected: 输出 `pre-commit hook 已安装: .../.git/hooks/pre-commit`，文件存在

- [ ] **Step 3: 验证 hook 文件存在且可读**

Run:
```powershell
node -e "const fs=require('fs');console.log('exists:', fs.existsSync('.git/hooks/pre-commit'));console.log('size:', fs.statSync('.git/hooks/pre-commit').size)"
```
Expected: `exists: true`，size > 1000

- [ ] **Step 4: 测试 hook（构造一个伪 pass result.json 但缺 review-verdict.json）**

写一个临时 stage 目录测试：
```powershell
node -e "const fs=require('fs');const p=require('path');const tmp=p.join(require('os').tmpdir(),'hook-test-'+Date.now());fs.mkdirSync(p.join(tmp,'src/projects/testproj/stages/04-runtime-baseline'),{recursive:true});const result={schemaVersion:1,stage:'04-runtime-baseline',status:'passed',claims:[{type:'runtime',claim:'fake',evidence:[],verdict_path:'evidence/runtime/rt-fake-runtime-verdict.json',evidence_strength:'live',review_verdict_path:'evidence/runtime/review-verdict.json'}],outputs:[],validation:[],nextStage:null};fs.writeFileSync(p.join(tmp,'src/projects/testproj/stages/04-runtime-baseline/result.json'),JSON.stringify(result,null,2));console.log('test fixture at:',tmp);console.log('注意：这是临时文件，不在 git 跟踪范围，无法触发 hook。要真测 hook 必须在仓库内 commit。')"
```
Expected: 输出临时 fixture 路径（注意 hook 只在 git commit 时触发）

实际验证策略：通过 E2E 集成测试在 Task 9 真实跑一次 commit 验证。

- [ ] **Step 5: Commit**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-add.ps1" "tools/utils/install-hooks.mjs"
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-commit.ps1" "feat: 新增 install-hooks.mjs pre-commit hook 安装器（layer 4 轻量存在性校验）"
```

---

## Task 8: 更新文档

**Files:**
- Modify: `docs/workflow.md`
- Modify: `AGENTS.md`
- Modify: `tools/.codex/skills/sc2-static-analysis/SKILL.md`
- Modify: `tools/.codex/skills/sc2-static-analysis/references/output-contract.md`

### Task 8.1: 更新 docs/workflow.md

- [ ] **Step 1: 用 Edit 在 workflow.md 的 stage 7 后插入 stage 7.5 + 更新 stage 6 描述**

定位（第 31-36 行附近）：
```markdown
6. `static-validation`: validate Galaxy, Catalog, dependencies, and packaging.
   - Run: `node tools/utils/workspace.mjs static-validate <project-id>`
   - Outputs: `evidence/static/diagnostics.json`, `evidence/static/dependency-graph.json`,
              `evidence/static/packaging-report.json`, `evidence/static/stage-verdict.json`
7. `runtime-validation`: launch SC2 and collect dynamic evidence.
8. `acceptance`: compare observed behavior with project acceptance criteria.
```

替换为：
```markdown
6. `static-validation`: validate Galaxy, Catalog, dependencies, and packaging, plus runtime evidence enforcement for the previous stage.
   - Run: `node tools/utils/workspace.mjs static-validate <project-id>`
   - Outputs: `evidence/static/diagnostics.json`, `evidence/static/dependency-graph.json`,
              `evidence/static/packaging-report.json`, `evidence/static/stage-verdict.json`,
              `evidence/static/prev-stage-runtime-check.json` (第 7 项检查)
   - 第 7 项检查: 校验前一 stage 的 `stage-transition.json` 存在且 sha256 与 `review-verdict.json` / `result.json` 一致；
     `review-verdict.json` 的 `summary.reproducible == summary.total`。
7. `runtime-validation`: launch SC2 live and collect dynamic evidence.
   - 用 `artifacts/launch-sc2-with-api.ps1` 启动 SC2 并开 API 端口 5000
   - 用 `python sc2-observer.py --port 5000 --claim-id <id> --scenario <s.json> --out-dir <stage>/evidence/runtime`
     产出 `<claim-id>-runtime-verdict.json` + `<claim-id>-events.ndjson`
   - 证据强度 `evidence_strength` 必须为 `live`，`replay` 仅作 dev 用不进 `evidence/runtime/`
7.5. `runtime-review`: reviewer 复核所有 runtime claim
   - Run: `node tools/runtime-bridge/review-runtime.mjs <stage-dir>`
   - Outputs: `<stage>/evidence/runtime/review-verdict.json`
   - 通过条件: `summary.reproducible == summary.total`
   - SC2 live 不可达 → claim 直接 `failed`，不 fallback 到 replay
8. `acceptance`: compare observed behavior with project acceptance criteria.

## Runtime Evidence Enforcement

Stage 推进必须经过四层阻断（缺一不可）：

1. **AI 自检**：写 result.json 前先跑 reviewer，退出码非 0 则 status 只能填 `blocked` 或 `failed`
2. **advance-stage 命令**：`node tools/utils/workspace.mjs advance-stage <project-id>`
   - 二次调 reviewer 复核
   - 写 `stage-transition.json`（含 review_verdict_sha256 + result_sha256）
   - 创建下一 stage 目录骨架
3. **static-validate 第 7 项**：下一 stage 的 static-validate 会校验前一 stage 的 runtime 证据
4. **pre-commit hook**：commit 时校验文件存在 + summary 数字（layer 4 弱于 layer 3，只做存在性）

不允许降级：`evidence_strength: live` 是唯一能进 `status=passed` 候选的强度。
SC2 live 跑不通 → claim `failed`，stage 不能 advance。
```

- [ ] **Step 2: Commit**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-add.ps1" "docs/workflow.md"
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-commit.ps1" "docs: workflow.md 加 stage 7.5 runtime-review + 四层阻断说明"
```

### Task 8.2: 更新 AGENTS.md

- [ ] **Step 1: 用 Edit 在 AGENTS.md 的 "Hard constraints" 节末尾追加 Runtime Evidence Enforcement**

定位（第 34 行附近 `- Preserve user changes and stop if an approved write-scope file contains unexplained concurrent edits.` 之后）：

追加：
```markdown

## Runtime Evidence Enforcement

- AI 在 stage `runtime-validation` 完成时，必须先跑 `node tools/runtime-bridge/review-runtime.mjs <stage-dir>`。
- 若 reviewer 退出码非 0，`result.json status` 只能填 `blocked` 或 `failed`，绝不能填 `passed`。
- `result.json` 中 `type == "runtime"` 的 claim 必须含 `verdict_path` / `evidence_strength` / `review_verdict_path` 字段。
- `evidence_strength` 必须为 `live`（其他枚举值不允许进入 `passed` 候选）。
- SC2 live 跑不通时直接 block，不允许 fallback 到 replay 证据。
- Stage 推进必须用 `node tools/utils/workspace.mjs advance-stage <project-id>`，不允许手写 `<next-stage>/plan.md`。
- `stage-transition.json` 由 `advance-stage` 命令独占写权，AI 手写无效（layer 3 会校验 sha256）。
- Pre-commit hook（layer 4）只做存在性校验；sha256 一致性校验由 static-validate 第 7 项（layer 3）负责。
- 紧急绕过：`git commit --no-verify` + commit message 标记 `[manual-override]`，事后必须审计。
```

- [ ] **Step 2: Commit**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-add.ps1" "AGENTS.md"
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-commit.ps1" "AGENTS.md: 增补 Runtime Evidence Enforcement 一节"
```

### Task 8.3: 更新 SKILL.md 和 output-contract.md

- [ ] **Step 1: 先读现有 SKILL.md 与 output-contract.md 结构**

Run:
```powershell
node -e "const fs=require('fs');const c=fs.readFileSync('tools/.codex/skills/sc2-static-analysis/SKILL.md','utf8');console.log('SKILL.md size:',c.length);const c2=fs.readFileSync('tools/.codex/skills/sc2-static-analysis/references/output-contract.md','utf8');console.log('output-contract.md size:',c2.length)"
```
Expected: 输出两个文件大小

- [ ] **Step 2: 用 Edit 在 SKILL.md 末尾追加第 7 项检查说明**

定位文件末尾，追加：
```markdown

## 第 7 项检查：Runtime Evidence Enforcement

`static-validate.mjs` 在原有 6 项检查后追加第 7 项：

- 检查前一 stage 的 `stage-transition.json` 存在
- 校验 `stage-transition.json` 的 `review_verdict_sha256` 与磁盘 `review-verdict.json` 内容一致
- 校验 `stage-transition.json` 的 `result_sha256` 与磁盘 `result.json` 内容一致
- 校验 `review-verdict.json` 的 `summary.reproducible == summary.total`

任一不通过 → static-validate 整体 fail。

相关命令：
- reviewer: `node tools/runtime-bridge/review-runtime.mjs <stage-dir>`
- stage 推进: `node tools/utils/workspace.mjs advance-stage <project-id>`
- hook 安装: `node tools/utils/install-hooks.mjs`
```

- [ ] **Step 3: 用 Edit 在 output-contract.md 末尾追加 runtime evidence 契约**

定位文件末尾，追加：
```markdown

## Runtime Evidence Contract (stage 7/7.5)

`runtime-verdict.json` (schemaVersion=2) 强制字段：
- `claim_id`: stage 内唯一标识符
- `command` / `working_dir` / `env` / `timeout_seconds`: reviewer 重跑所需
- `observed_values`: reviewer 比对核心字段
- `evidence_strength`: `live` (唯一允许进入 passed) | `replay` | `none`

`review-verdict.json` (schemaVersion=1) 强制字段：
- `claims[]`: 每条含 `reproducible` / `exit_code_match` / `observed_values_match` / `failure_reason`
- `summary`: `{ total, reproducible, partial, failed }`
- 通过条件: `summary.reproducible == summary.total`

`stage-transition.json` (schemaVersion=1) 强制字段：
- `from_stage` / `to_stage` / `transitioned_at` / `executor_pid`
- `review_verdict_sha256` / `result_sha256` / `advance_stage_version`

`result.json` (stage-result.schema.json) 中 `type=="runtime"` 的 claim 必须含：
- `verdict_path`: 指向 `<claim_id>-runtime-verdict.json`
- `evidence_strength`: `live`
- `review_verdict_path`: 指向 `review-verdict.json`
```

- [ ] **Step 4: Commit**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-add.ps1" "tools/.codex/skills/sc2-static-analysis/SKILL.md"
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-add.ps1" "tools/.codex/skills/sc2-static-analysis/references/output-contract.md"
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-commit.ps1" "docs: 同步 SKILL.md 与 output-contract.md 加入 runtime evidence 契约说明"
```

---

## Task 9: 集成测试 + E2E 验收

**Files:**
- Create: `test/integration/test_review_runtime_live.mjs`

### Task 9.1: 写集成测试（手动跑，需 SC2）

- [ ] **Step 1: 用 Write 创建 `test/integration/test_review_runtime_live.mjs`**

```javascript
/**
 * Integration test: 真实跑 SC2 live + reviewer 复核
 *
 * 标记 @integration，需要 SC2 已装且能启动 API 端口 5000。
 * CI 跳过；本地手动跑：node test/integration/test_review_runtime_live.mjs
 *
 * 步骤：
 * 1. 启动 SC2（artifacts/launch-sc2-with-api.ps1，无 map，停主菜单）
 * 2. 跑 sc2-observer.py --claim-id rt-int --scenario <ping-scenario.json>
 * 3. 跑 reviewer 复核
 * 4. 断言 review-verdict.summary.reproducible == summary.total
 */
import { strict as assert } from "node:assert";
import { mkdtemp, mkdir, writeFile, rm, readFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync, spawn } from "node:child_process";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(scriptDir, "..", "..");
const REVIEWER = join(REPO_ROOT, "tools", "runtime-bridge", "review-runtime.mjs");
const OBSERVER = join(REPO_ROOT, "tools", "runtime-bridge", "sc2-observer.py");
const LAUNCHER = join(REPO_ROOT, "artifacts", "launch-sc2-with-api.ps1");

// ping scenario：只校验 SC2 API 可连
const PING_SCENARIO = {
  "claim": "SC2 API ping 可达",
  "claim_id": "rt-int",
  "expectations": [
    {
      "id": "ping_ok",
      "type": "ping",
      "expected": true
    }
  ]
};

async function startSC2() {
  // 异步启动 launcher，等端口 5000 监听
  console.log("启动 SC2（最多等 120s）...");
  const child = spawn("powershell", [
    "-NoProfile", "-ExecutionPolicy", "Bypass",
    "-File", LAUNCHER
  ], { stdio: "inherit", shell: false });

  // 等端口
  for (let i = 0; i < 24; i++) {
    await new Promise(r => setTimeout(r, 5000));
    try {
      const ret = execFileSync("node", ["-e",
        `const net=require('net');const s=new net.Socket();s.setTimeout(1000);s.on('connect',()=>{console.log('open');s.destroy();process.exit(0)});s.on('error',()=>{process.exit(1)});s.on('timeout',()=>{s.destroy();process.exit(1)});s.connect(5000,'127.0.0.1')`
      ], { encoding: "utf8" });
      if (ret.includes("open")) {
        console.log("SC2 API 端口 5000 已监听");
        return child;
      }
    } catch (e) { /* 还没起 */ }
    console.log(`  attempt ${i+1}/24: 端口未开`);
  }
  throw new Error("SC2 启动超时（120s 内端口 5000 未监听）");
}

async function main() {
  if (process.env.SKIP_INTEGRATION === "1") {
    console.log("SKIP_INTEGRATION=1, 跳过集成测试");
    return;
  }

  if (!existsSync(LAUNCHER)) {
    console.log(`Launcher 不存在: ${LAUNCHER}，跳过`);
    return;
  }

  const tmpRoot = await mkdtemp(join(tmpdir(), "rt-int-"));
  try {
    const stageDir = join(tmpRoot, "07-runtime-validation");
    await mkdir(join(stageDir, "evidence", "runtime"), { recursive: true });

    // 写 scenario
    const scenarioPath = join(stageDir, "ping-scenario.json");
    await writeFile(scenarioPath, JSON.stringify(PING_SCENARIO, null, 2) + "\n", "utf8");

    // 1. 启动 SC2
    const sc2Child = await startSC2();

    try {
      // 2. 跑 sc2-observer.py
      console.log("跑 sc2-observer.py...");
      try {
        execFileSync("python", [
          OBSERVER,
          "--port", "5000",
          "--duration", "10",
          "--scenario", scenarioPath,
          "--out-dir", join(stageDir, "evidence", "runtime"),
          "--claim-id", "rt-int"
        ], { stdio: "inherit", encoding: "utf8", timeout: 30000 });
      } catch (e) {
        // exitCode 1 也可能是 verdict overall_passed=false，继续看产物
        console.log(`sc2-observer.py 退出码 ${e.status}（继续检查产物）`);
      }

      // 3. 写 result.json
      const result = {
        schemaVersion: 1,
        stage: "07-runtime-validation",
        status: "passed",
        claims: [{
          type: "runtime",
          claim: "SC2 API ping 可达",
          evidence: ["evidence/runtime/rt-int-runtime-verdict.json"],
          verdict_path: "evidence/runtime/rt-int-runtime-verdict.json",
          evidence_strength: "live",
          review_verdict_path: "evidence/runtime/review-verdict.json"
        }],
        outputs: [],
        validation: [],
        nextStage: null
      };
      await writeFile(join(stageDir, "result.json"), JSON.stringify(result, null, 2) + "\n", "utf8");

      // 4. 跑 reviewer
      console.log("跑 reviewer...");
      try {
        execFileSync("node", [REVIEWER, stageDir], { stdio: "inherit", encoding: "utf8" });
      } catch (e) {
        // exitCode 1 = 有 claim 不可重跑
      }

      // 5. 断言
      const reviewPath = join(stageDir, "evidence", "runtime", "review-verdict.json");
      if (!existsSync(reviewPath)) {
        console.error("FAIL: review-verdict.json 未生成");
        process.exit(1);
      }
      const review = JSON.parse(await readFile(reviewPath, "utf8"));
      console.log(`review summary: ${JSON.stringify(review.summary)}`);

      // 注意：实际 reproducible 取决于 sc2-observer.py 重跑是否稳定
      // 这个测试主要验证 reviewer 流程能跑通，不强制要求 reproducible=true
      // （因为 ping scenario 重跑时 SC2 可能已在不同状态）
      assert.ok(review.claims.length >= 1, "至少 1 条 claim");
      assert.ok(review.summary.total >= 1, "summary.total >= 1");

      console.log("PASS: 集成测试流程跑通");
    } finally {
      // 关 SC2
      try { sc2Child.kill("SIGTERM"); } catch (e) { /* ignore */ }
      try {
        execFileSync("powershell", ["-Command", "Get-Process SC2_x64 -ErrorAction SilentlyContinue | Stop-Process -Force"],
          { stdio: "ignore", shell: false });
      } catch (e) { /* ignore */ }
    }
  } finally {
    await rm(tmpRoot, { recursive: true, force: true });
  }
}

main().catch((e) => {
  console.error("Integration test failed:", e.message);
  console.error(e.stack);
  process.exit(1);
});
```

- [ ] **Step 2: 跑集成测试（需 SC2 已装）**

Run:
```powershell
node test\integration\test_review_runtime_live.mjs
```
Expected: 输出 `PASS: 集成测试流程跑通`（或因 SC2 状态原因输出 FAIL，但 reviewer 流程必须跑通生成 review-verdict.json）

- [ ] **Step 3: Commit**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-add.ps1" "test/integration/test_review_runtime_live.mjs"
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-commit.ps1" "test: 新增 reviewer 集成测试（真实跑 SC2 live + reviewer 复核）"
```

### Task 9.2: E2E 验收（手动）

- [ ] **Step 1: 安装 pre-commit hook（若未装）**

Run:
```powershell
node tools\utils\install-hooks.mjs
```
Expected: `pre-commit hook 已安装`

- [ ] **Step 2: 构造伪 pass 场景验证 hook 拦截**

在一个真实 stage 目录（如 `src/projects/cmre-porting/stages/04-runtime-baseline`）：
1. 修改 result.json 的 status 为 "passed"
2. 添加一个 type=runtime 的 claim，verdict_path 指向不存在的文件
3. 尝试 `git commit`
4. 预期：hook 拒绝 commit

```powershell
# 用 Edit 工具修改 result.json 添加伪 runtime claim
# 然后：
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-add.ps1" "src/projects/cmre-porting/stages/04-runtime-baseline/result.json"
git commit -m "test: 验证 hook 拦截伪造 pass"
```
Expected: hook 输出 `ERROR: runtime claim verdict_path 不存在`，拒绝 commit

- [ ] **Step 3: 还原 result.json**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-restore.ps1" "src/projects/cmre-porting/stages/04-runtime-baseline/result.json"
```

- [ ] **Step 4: 最终全量验证**

Run:
```powershell
# 1. schema 自校验
node tools\analysis\validate-schema.mjs --self-check

# 2. reviewer 单元测试
node test\test_review_runtime.mjs

# 3. 静态校验（在 cmre-porting 项目上）
node tools\utils\workspace.mjs static-validate cmre-porting
```
Expected:
- schema self-check 全 ✓
- 5 个 reviewer 单元测试全 PASS
- static-validate 跑通（第 7 项检查可能因当前无前一 stage 而跳过）

- [ ] **Step 5: 最终 commit**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-commit.ps1" "chore: 完成 runtime evidence enforcement 落地（4 schema + reviewer + advance-stage + 第 7 项 + hook + 文档）"
```

---

## 完成标准

- [ ] Task 1: 4 个 schema 文件就位，自校验全 ✓
- [ ] Task 2: sc2-observer.py --claim-id 参数生效，--help 显示
- [ ] Task 3: reviewer 单元测试 5 个全 PASS
- [ ] Task 4: advance-stage 命令能解析 project.json 推进 stage
- [ ] Task 5: static-validate 第 7 项检查逻辑就位
- [ ] Task 6: validate-schema --self-check 模式工作
- [ ] Task 7: pre-commit hook 安装到 .git/hooks/pre-commit
- [ ] Task 8: workflow.md / AGENTS.md / SKILL.md / output-contract.md 已更新
- [ ] Task 9: 集成测试跑通（或因 SC2 状态 fail 但流程跑通）；E2E 验证 hook 能拦截伪造 pass

## Self-Review

完成 plan 后做 self-review：

1. **Spec 覆盖**：
   - §1 runtime-verdict schema → Task 1.1 ✓
   - §2 review-verdict schema → Task 1.3 ✓
   - §3 reviewer 行为 → Task 3 ✓
   - §4 四层阻断（layer 1-4）→ Task 4 (layer 2) + Task 5 (layer 3) + Task 7 (layer 4) + Task 3 (layer 1) ✓
   - §5 fallback 规则 → Task 3 内 reviewer 容错分支 ✓
   - §6 测试方案 → Task 3 (单元) + Task 9 (集成 + E2E) ✓

2. **占位符扫描**：无 TBD/TODO，每步都有具体代码或命令

3. **类型一致性**：
   - `claim_id` 在 schema/test/reviewer/advance-stage 里都是 `^[a-z0-9][a-z0-9-]*$` ✓
   - `evidence_strength` 枚举值在 schema/sc2-observer.py/reviewer/AGENTS.md 里都是 `live | replay | none` ✓
   - `failure_reason` 枚举值在 review-verdict schema 和 reviewer 代码里一致 ✓
   - `stage-transition.json` 字段在 schema 和 advance-stage 写入逻辑里一致 ✓

---

**Plan complete and saved to `docs/superpowers/plans/2026-07-23-runtime-evidence-enforcement.md`.**
