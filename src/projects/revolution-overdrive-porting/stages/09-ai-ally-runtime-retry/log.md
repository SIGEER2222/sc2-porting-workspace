# Stage 09 Log: AI Ally Runtime Retry

> **2026-08-09 重写。** 本文件此前描述的是一套「运行时观测联盟契约」实现
> (`RuntimeAllianceObservation` / `build_runtime_observed_ally_contract`)，该实现已在
> C-lite 收口 (`git reset --hard origin/master`) 时被回退，仓库中并不存在；其"5/5 通过"
> 的验证记录因此是失真的。旧内容已整体作废，本文件改为记录 Stage 09 的**真实目标与真实结果**：
> 拿到一个稳定、无 debug 的原生窗口，跑未经修改的 Stage 08 护送探针。

## Plan execution

1. **Preflight.** 完成。SC2 以 `SC2Switcher_x64.exe -listen 127.0.0.1 -port 5000 -debug`
   起 API 实例（PID 23692，13:39:50），5000/6119 均 LISTEN。
2. **Native runtime attempt.** 完成。运行源码受控、未改动的
   `stages/08-ai-ally-native-closure/p2_handover_probe.py`：
   - `CreateGame` → `init_game`，`nested_error=0`，`errors=[]`
   - `JoinGame` → `in_game`，`player_id=1`
   - Catalog 非空（12225 abilities）
   - 观测持续推进：baseline loop 88 → final loop 1465
3. **Evidence decision.** 判定为 `passed`。P2 拿到单位是**地图自身**的 rescue 生命周期所致，
   非探针制造。
4. **Closure.** 更新 log / result / issues / self-assessment，新增两条确定性守卫，
   并补做同窗口 ScriptError 扫描。

## 目标选择修正（此前 blocked 的真因）

Stage 09 上一轮记录的阻塞原因是"外部 SC2 占用 port-5000 lease"。这只是表层。本轮先按
2026-08-09 用户授权清掉外部实例、重起 API 模式，`create_game` **仍然**失败，
`nested_error=2 (missing_mod)`。逐步排除：

- 复制 `RevolutionOverdrive.SC2Mod`(604MB) 到 `Documents\StarCraft II\Mods\` —— 仍失败
- 补齐完整依赖链（`CovertOps` / `1钢铁之翼` / `Umojan` / `33克哈` / `9海盗2333` +
  `Campaigns\Void.SC2Campaign`）—— 仍失败

真因是**地图选错**：探针是为 `thorner03` 硬编码的（`GATE_UNIT_TYPE="TychusCommando"`、
`REGION24_CENTER=(89.1628, 41.6557)`、`RescueUnit(UnitFromId(2), gv_p02_TYCHUS)`），
却被指向了 `packages/Maps/thanson03b.SC2Map` 这个**文件夹地图**。改指向
`artifacts/.../stage07-commander-closure/thorner03.stage07.packed.SC2Map`（单文件打包图，
正是 Stage 07 成功用过的那份）后一次通过。

> 教训：`create_game nested_error=2` 会把"地图/依赖不可解析"混为一谈。先确认**探针与地图是否同一张图**，
> 再去怀疑 mod 依赖，可省掉搬运 600MB 的弯路。

## Runtime evidence

| 项 | 观测 |
| --- | --- |
| verdict | `passed_native_p2_handover_observed` |
| map | `thorner03.stage07.packed.SC2Map` |
| gate | Tychus 于 loop **939** 进入 Region 24（native P1 order，`gate_method=escort_native_tychus`） |
| handover | Odin `tag 4294967297` 于 loop **1273** 归属 P2 |
| 归属迁移 | loop 1225 `owner=16, alliance=3`（可救援中立） → loop 1273 `owner=2, alliance=2`（P1 视角 = ALLY） |
| 稳定性 | loop 1465 仍为 P2 所有，HP 2500/2500 |
| 未被制造 | `map_edits=false`、`adapter_created_p2_units=false`、`generic_melee_ai_injected=false`、`debug_apis_used=[]` |
| ScriptError | 窗口内 0 个 `*ScriptError*.txt` |

`alliance=2` 尤其关键：这是 **P1 自己的观测**读出来的 ALLY 关系，不是从名单推断的。

## 治理修复：被藏起来的守卫

排查过程中发现 `test_runtime_observed_contract.py` 引用了已被回退的符号，收集期即 ImportError；
它此前被 `conftest.collect_ignore_glob` 排除以恢复绿色，副作用是此后每轮门禁都报
"32 passed" 而**没有任何信号**提示该守卫其实从未运行。

处置：删除该孤儿测试 → 清空排除列表 → 新增 `test_collection_integrity.py` 元守卫
（非空 ignore 列表即红；任何 test 模块 import 失败即红）。做了阳性对照：人为造一个坏测试
并藏起来，两条守卫同时报红；还原后 11 passed。

## Validation evidence

- `p2_handover_probe.py --port 5000 --map-path <packed thorner03> --out-dir <stage09>` → exit 0，
  `verdict=passed_native_p2_handover_observed`
- `python -m pytest src/projects/revolution-overdrive-porting -q` → **43 passed**（此前 32）
- `python -m pytest .../stages/09-ai-ally-runtime-retry -q` → **11 passed**（离线，不需要 SC2）
- 阳性对照（藏坏测试）→ 2 failed as designed，还原后 11 passed
- 同窗口 GameLogs 扫描 → `scriptErrorFiles: []`，`verdict=no_script_error_in_window`

## Scope and source integrity

- 只改动 Stage 09 目录、项目 `conftest.py` 与 Stage 09 artifacts。
- `vibe/ai_ally.py` **未改动**（HEAD 干净），RO-AI-001 的 182/18 口径保持不变。
- 只读下载源未被编辑；探针对地图脚本只读。
