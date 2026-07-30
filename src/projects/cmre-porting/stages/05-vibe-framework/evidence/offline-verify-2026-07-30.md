# 离线验证报告 — SC2 Vibe 调试框架（galaxy-vibe 工具链）

- 日期：2026-07-30
- 范围：对 `tools/galaxy-vibe/` 与 `src/projects/cmre-porting/vibe/` 现有工具链做**离线**（无运行 SC2）验证。
- 结论：你贴的「双循环实施计划结论」对应外部 `sc2-vibe完整实施计划.md`（2026-07-29），
  其要求的前置动作（关闭旧 baseline + 声明 writeScope）**本地已完成**，设计已被
  `artifacts/galaxy-vibe/plan.md`(v2) 与 `src/projects/cmre-porting/stages/05-vibe-framework/` 吸收并超越。
  本验证仅确认「代码层已落地且离线可验」，真机 runtime 证据仍需桌面 SC2。

## 方法
- 受管 Python：`C:/Users/Sigeer/.workbuddy/binaries/python/versions/3.13.12/python.exe`
- 语法：`python -m py_compile` 全部 8 个 .py
- 功能：纯 Python 运行器（`tempfile` 建临时目录 → `subprocess` 调各工具 → 断言退出码/输出），覆盖 P0/ P3/ P4 / 一键收口。
- 临时目录放在仓库内 `.workbuddy/verify_tmp/`（gitignore，避免污染 writeScope）。

## 结果

| 项 | 命令 / 文件 | 结果 |
|---|---|---|
| 语法编译 | 8 个 .py（含 project 级 protocol/transport_probe、artifacts 级 6 个） | **8/8 OK** |
| P0 传输闸门（项目级 mock 自测） | `src/projects/cmre-porting/vibe/transport_probe.py --selftest` | **PASS** 5 项全绿（20 ping ack / 重复 ID 仅执行一次 / 5 非法零副作用 / p95≤2s / session 恢复拒绝旧请求），退出 0 |
| P4 cold_cycle | snapshot / check 无变更 / check 修改 / emit-reset | **4/4 PASS** |
| ScriptError 闸门 | 近期错误检出(count1,exit1) / 无新增(count0,exit0) | **2/2 PASS** |
| 一键收口 summarize_verdict | 4 用例（assert全过+无SE→PASS / +SE→FAIL / assert败→FAIL / 无assert+无SE→PASS） | **4/4 PASS** |
| P3 visual_loop 算法 | `--selftest`（合成图 diff + 稳态判定） | **1/1 PASS** |
| 运行时模块（aiohttp 依赖） | `galaxy_repl.py`、`tools/galaxy-vibe/transport_probe.py` | 编译 OK；**沙箱 import 受阻**（受管 Python 无 aiohttp），真机有，非代码缺陷 |

汇总：功能断言 **12/12 PASS**，编译 **8/8 OK**；2 个模块因缺 `aiohttp` 仅能静态编译，运行需桌面环境。

## 与结论/RPC 契约对照
- RPC 契约（protocol_version/session_id/request_id/sequence/operation/args/issued_at/checksum；ack\|result\|error；幂等 + 过期 session/乱序/坏校验和/未知操作拒绝）已由 `src/projects/cmre-porting/vibe/protocol.py` 实现，且 `--selftest` 实证通过。
- MVP 白名单（system.ping / scenario.reset / unit.spawn/kill/set_vital / player.set_resource / query.* / visual.actor_* / assert.*）已在 `protocol.py` 中逐项登记。
- 三路真机 transport（bank_reload / sc2api_chat / input_fallback）以 guarded 适配器存在，沙箱跳过；`transport-verdict.json`（mock）已落地。

## 真实缺口（需桌面，非代码问题）
1. 真机 transport 实证：BankReload / SC2API Chat / 输入回退三路 ack、去重、p95 实测选型。
2. `galaxy_repl.py` 联调：spawn/kill/set/query/call 在运行 SC2 中实测（依赖 aiohttp + `/sc2api`）。
3. P3 实时采集（mss 窗口截图 + 固定镜头 CameraPan native 待验证）。
4. 统一入口 `tools/launchers/vibe.ps1`（probe|hot|verify|rebuild|run-task）**尚未创建**——结论里唯一点名但缺位的文件。
5. P5 意图路由 / P6 第二消费者 / P7 soak 稳定性：未开始。

## 验证脚本（已清理）
验证用临时运行器放在 `C:/Users/Sigeer/.workbuddy/verify_runner.py`，跑完即删；未向仓库提交任何新代码。
