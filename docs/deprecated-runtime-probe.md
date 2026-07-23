# Deprecated: RuntimeProbe as runtime evidence

> **状态**：已禁用（DEPRECATED，禁止作为 runtime 证据使用）
> **生效时间**：2026-07-23
> **替代方案**：`tools/runtime-bridge/sc2-observer.py` over SC2 API websocket (`-listen 127.0.0.1 -port <port>`)，由 `launch-cmre-alenger.ps1 -ListenPort <port>` 触发；详见 [2026-07-23-runtime-evidence-enforcement-design.md](./superpowers/specs/2026-07-23-runtime-evidence-enforcement-design.md)

## 范围

"RuntimeProbe" 指：

- `Mods/RuntimeProbe/RuntimeProbe.SC2Mod` 依赖包
- `LibRuntimeProbe_h.galaxy` / `LibRuntimeProbe.galaxy` 触发库
- 注入到 `MapScript.galaxy` 的 `include "LibRuntimeProbe"` 与 `libRuntimeProbe_InitLib()` 调用
- 注入到 `BankList.xml` 的 `RuntimeProbe` Bank 注册
- 通过 `BankLoad("RuntimeProbe", 1)` + `BankValueSetFromString` 写出的任何诊断键
- 任何在 stage `result.json` / `runtime-verdict.json` / `issues.json` / `runtime-eligibility.json` / `log.md` 中把 RuntimeProbe Bank 输出当作 runtime pass 证据的引用
- launcher 上的 `-EnableRuntimeProbe` / `-ProbeDuration` 开关（legacy-project 的 runtime-probe 机制同属禁用范围）

## 禁用原因

1. **证据强度不足**：RuntimeProbe Bank 输出是 map 内 Galaxy 代码自己写的，没有独立 reviewer 重跑复核，等同于"AI 自写自审"。在 [runtime-evidence-enforcement-design.md](./superpowers/specs/2026-07-23-runtime-evidence-enforcement-design.md) 的四层门禁下，不满足"层 1 AI 自检 → reviewer 重跑 → 比对 observed_values"的可重跑要求。
2. **断言集合不闭合**：历史上 RuntimeProbe 在 stage 02/03 的 `runtime-eligibility.json` 中被标记为 "cannot prove commander identity, loaded mods, or build-panel correctness with its current empty assertions"。即使后续补全也仍属自写自审。
3. **可被绕过**：`-EnableRuntimeProbe` 是 launcher 开关，AI 只要在 launcher 命令行里加上就能产出"绿色心跳"verdict，但心跳本身不证明 commander/build panel 真的可用。
4. **API 模式冲突**：在 SC2 API 模式（`-listen 127.0.0.1 -port <port>`）下，RuntimeProbe 周期触发器与 API websocket 抢占 Bank 写入句柄，曾导致崩溃；已于 commit 中将其 `libRuntimeProbe_gf_StartProbe()` 调用注释掉。
5. **设计文档已明确禁用方向**：runtime-evidence-enforcement-design.md §5 不允许降级，唯一允许进入 `passed` 候选的证据强度是 `live`（SC2 API 实时观察），RuntimeProbe Bank 不在此列。

## 禁用规则

| 行为 | 是否允许 |
|------|----------|
| 在 launcher 中 `Copy` `LibRuntimeProbe*.galaxy` 到 map | ❌ 禁止 |
| 在 `MapScript.galaxy` 注入 `include "LibRuntimeProbe"` / `libRuntimeProbe_InitLib()` | ❌ 禁止 |
| 在 `BankList.xml` 注册 `RuntimeProbe` Bank | ❌ 禁止 |
| 在 Galaxy 代码中 `BankLoad("RuntimeProbe", ...)` 写诊断键 | ❌ 禁止 |
| 在 launcher 上加 `-EnableRuntimeProbe` / `-ProbeDuration` | ❌ 禁止 |
| 把 RuntimeProbe Bank 输出写入 `evidence/runtime/` 当 runtime pass 证据 | ❌ 禁止 |
| 在 stage `result.json` / `runtime-verdict.json` 把 RuntimeProbe 报告列为 `evidence` | ❌ 禁止 |
| 引用 `legacy-project:scripts/runtime-probe/` 下的产物作为 runtime 证据 | ❌ 禁止 |
| 在 `cmre-alenger-dependencies.json` 等依赖清单中声明 `RuntimeProbe.SC2Mod` | ❌ 禁止 |
| 读取 RuntimeProbe Bank 做 debug 排查（不进入 stage 证据链） | ✅ 允许（仅排查用，不写入 `evidence/`） |

## 已清理的位置

下列位置已在 2026-07-23 的禁用动作中移除 RuntimeProbe 引用：

- `tools/launchers/launch-cmre-alenger.ps1`：删除 galaxy 文件拷贝、BankList 注册、`include "LibRuntimeProbe"`、`libRuntimeProbe_InitLib()`、`BankLoad("RuntimeProbe", ...)` 诊断写入
- `src/projects/cmre-porting/packages/Mods/7vs1/Alenger3Adapter.SC2Mod/Base.SC2Data/LibA3ADAPTER.galaxy`：删除 adapter 启动时的 RuntimeProbe Bank 诊断
- `src/config/cmre-alenger-dependencies.json`：从 `baseMods` / `baseDependencyPaths` 移除 `RuntimeProbe.SC2Mod`
- `src/projects/reborn-zexpedition03-raynor-mvp/manifests/runtime-scenario.json`：从 launcher arguments 移除 `-EnableRuntimeProbe -ProbeDuration 300`
- `src/projects/reborn-zexpedition03-raynor-mvp/project.json`：从 `writeScope` 移除 `legacy-project:scripts/runtime-probe/normalize_probe.py`
- `evidence/runtime-probe/` 目录：整体删除（旧 replay-decode 产物，不符合新 schema，详见设计文档 §6 风险点 6）
- 各 stage 历史 `result.json` / `log.md` / `issues.json` / `runtime-eligibility.json` / `runtime-verdict.json` 中显式提到 RuntimeProbe 的行

## 后续 AI 必须遵守

1. **不要再恢复** RuntimeProbe 注入逻辑。若需要 runtime 证据，使用 `sc2-observer.py` + SC2 API websocket。
2. 若 launcher 在某环境下无法开 API 端口（switcher 丢弃 `-listenPort` 等已知问题），直接标 `result.status = blocked`，**禁止 fallback 到 RuntimeProbe Bank** 作为 pass 证据。
3. 若发现新代码引入 `BankLoad("RuntimeProbe", ...)` / `include "LibRuntimeProbe"` / `-EnableRuntimeProbe`，视为违反本规则，必须改回。
4. 任何 runtime 证据必须满足 [runtime-evidence-enforcement-design.md](./superpowers/specs/2026-07-23-runtime-evidence-enforcement-design.md) §1 的 schema 与 §5 的降级禁令。
