# Galaxy Vibe P0/P1 真机贯通报告（2026-08-08）

## 结论

**P0（传输层）与 P1（RPC 真改变游戏世界）双双真机 PASS，全程无人工干预。**

| 门禁 | 结果 | 证据工件 |
| --- | --- | --- |
| P0-A 内核注册 | PASS ×2（可复现） | `artifacts/galaxy-vibe/p0-probe-v2-verdict.json` / `-run2.json` |
| P0-B RPC 往返（`system.ping` → pong） | PASS ×2 | 同上 |
| P1-A Kernel 执行 `unit.spawn` | PASS | `artifacts/galaxy-vibe/p1-probe-verdict.json` |
| P1-B SC2 raw observation 增量 | PASS（Marine +5） | 同上 |
| P1-C Kernel 自查 `query.units` 一致 | PASS（count=5） | 同上 |
| **反向对照**（无效 `unit_type`） | **正确 FAIL**（`delta={}`） | `artifacts/galaxy-vibe/p1-probe-negative-control.json` |

汇总裁决：`artifacts/galaxy-vibe/transport-verdict.json`（schemaVersion 2）。

链路全貌：

```
Host(Python) ──写 GalaxyVibe.SC2Bank──▶ Kernel PollLoop(Wait 0.5s 轮询)
                                              │
                                     dispatch operation
                                              │
                                       Galaxy UnitCreate()
                                              │
        ┌─────────────────────────────────────┼──────────────────────┐
        ▼                                     ▼                      ▼
  response/<rid> 回写 Bank          SC2 raw observation        Kernel query.units
  {"error_code":"OK",               Marine +5（第三方          count=5
   "payload":{"created":5}}          ground truth）
```

## 关键纠正：不需要人工点编辑器 Save

`docs/galaxy-vibe-real-machine-status.md` 此前的核心结论是：

> SC2 运行时**只认已编译的 `Triggers` 二进制**，`.galaxy` 源仅供编辑器使用；编译
> `Triggers` 的唯一工具是 SC2 Editor GUI，无 CLI / 无头编译。因此必须人点一次 Save。

**这条结论已被证伪。** 本次 P0/P1 全程**没有打开过编辑器**：

1. 把 Vibe 源 `.galaxy` 放进地图目录镜像的 `Base.SC2Data/`；
2. 用 `tools/galaxy-vibe/wire_map_includes.py` 在 `MapScript.galaxy` 里插入 include 块；
3. 用 `tools/galaxy-vibe/pack_map_mirror.py` 把目录镜像打成 `.SC2Map`（MPQ）；
4. 经 SC2API `create_game(local_map=LocalMap(map_data=...))` 字节直传加载。

SC2 在加载地图时会**自己编译 `MapScript.galaxy` 及其 include 闭包**。之前之所以
一直失败并被归因为"缺一次 Save"，真实原因是下面两条编译错误——它们让整个
MapScript 加载失败，表现为"脚本没跑"，被误读成"Triggers 没编译"。

## 真正的两个根因

### 根因 1：`LibVibeHandles.galaxy` 对 struct 类型按值传参

SC2 编译器报（`GameLogs/2026-08-08 14.17.04 ScriptError.txt`）：

```
LibVibeHandles.galaxy:649/652/656/661  仅能传递基础类型 / 不支持大容量复制
```

句柄表生成器把 `libCOTF_gs_HistogramData`（用户 **struct**）套用了标量模板，
生成了 `HistogramData[513]` 全局数组 + 按值传参/赋值。Galaxy 硬限制：struct
不能按值传参（必须 `structref`）、不能整体赋值复制。

生成器 `src/projects/cmre-porting/stages/26-full-function-invoke/generate_invoke_adapters.py`
其实**已经修成 fail-closed**，但四个 `LibVibeHandles.galaxy` 副本全是旧版——
改了生成器却从未重新生成+分发。重跑生成器即解决。

### 根因 2：MapScript include 闭包断裂

Galaxy 是**单遍编译 + 无跨编译单元链接**：`MapScript.galaxy` 的 include 闭包
就是唯一编译单元。闭包里缺任何被调用的符号 → 整个 MapScript 加载失败 →
`InitMap()` 永不执行 → Kernel 永不注册。

断裂点有两处：

- `LibVibeKernel.galaxy` 调 `libVibeHandles_gf_Clear_*`、`LibVibeKernel_h.galaxy`
  引用 `libVibeInvoke_gf_Dispatch`，但两者都不在闭包里；
- `MapScript.galaxy` 的 `InitMap()` 调 `libMapModBridge_gf_WriteDebugBank(...)`，
  但 `LibMapModBridge.galaxy` 也不在闭包里。

`wire_map_includes.py` 新增 `tier0` 档与 `PREREQ_LIBS` 机制后一次接线到位：

```
include "LibMapModBridge"
include "LibVibeKernel_h"
include "LibVibeHandles"
include "LibVibeInvokeDispatch_active"
include "LibVibeKernel"
```

## 诊断方法论（可复用）

### 分层判定 L1–L4

`tools/galaxy-vibe/map_load_diag.py` 用**可观测单位数**把粗糙的"探针 FAIL"切成四层：

| 层 | 现象 | 含义 |
| --- | --- | --- |
| L1 | create_game / join_game 失败 | 地图根本没进游戏 |
| L2 | 进游戏但单位数 ≈ 0 | MapScript 未执行（编译/加载失败） |
| L3 | 有单位、无 bank | MapScript 跑了但 Kernel 没注册 |
| L4 | 有 bank | 检查 key 完整性 |

### proto2 optional enum 陷阱（踩了整整一轮）

`ResponseCreateGame.error` / `ResponseJoinGame.error` 是 **proto2 optional enum**。
proto2 未设置的 optional enum **读出来是默认值 = 枚举首项 = 1**
（`MissingMap` / `MissingParticipation`）。所以：

```python
if r.join_game.error:      # ❌ 成功时也恒为真，把每次成功误判成失败
if r.HasField("join_game") and r.join_game.HasField("error"):   # ✅ 唯一可靠判定
```

这个坑让 `map_load_diag.py` 连续误报 L1，掩盖了真实的 L2。已在
`map_load_diag.py:_sub_err()` 里注释钉死。

### 三方交叉验证（P1 探针设计）

只信 Kernel 自述会自证。`tools/galaxy-vibe/p1_probe.py` 要求三条独立证据同时成立：

1. **Kernel 响应**：`response/<rid>` 里 `error_code=OK` 且 `payload.created=N`；
2. **第三方观测**：SC2API raw observation 里玩家单位数恰好 `+N`，且增量类型正确
   （**不经 Bank、不经 Kernel**，是真正的 ground truth）；
3. **Kernel 自查**：再发一条 `query.units`，Kernel 数出的数量与 ② 一致。

并配**反向对照**：请求一个不存在的 `unit_type`，必须 FAIL 且 `delta={}`。
没有反向对照，正向 PASS 无法排除缓存/残留假阳性。

## 已知遗留缺陷

### VIBE-KERNEL-001：handler 异常中止会静默丢响应（新发现，open）

反向对照暴露：`unit.spawn` 传入不存在的 `unit_type` 时，Kernel **不回任何响应**，
客户端只能等超时。代码里明明写了返回 `INVALID_ARGS`，但
`CatalogEntryIsValid(c_gameCatalogUnit, "<不存在的条目>")` 会触发 Galaxy 运行时错误，
把该次 trigger 执行整个中止在写响应之前。PollLoop 本身存活（后续 `query.units` 正常）。

**修复设计**：解析出 `request_id` 后**先悲观写一条 `HANDLER_ABORTED` 响应**，
再执行 handler 并用真实结果覆盖。这样任何 handler 中止都变成可见错误而非客户端挂起。

### GEN-SCOPE-001：invoke 生成器不按地图依赖闭包过滤（新发现，open）

`generate_invoke_adapters.py`：

- 第 187–190 行 `funcref_candidates` 是**全局**收集（整个 catalog 的 `void(int)`），
  不按地图过滤；
- 第 195 行 `bundles[m]` 的筛选只要求 `d.startswith("Mods/")`，等于把**所有** mod
  的符号都塞进每张图。

后果：`亡者之夜` 只依赖 `CMRE_Core_Base/Triggers/Mengsk/Stetmann` + `CMRE_BuffPatch`，
却被塞进了 `CoreRuntime.SC2Mod` 的 `XMChallenge_*` / `XMBlessing_*` / `XMProgression_*`。
这些符号在本图编译单元里不存在 → 编译器在
`LibVibeInvokeCommon.galaxy:254` 报"解析返回时出错" → 脚本读取失败。

**修复设计**：从每张图的 `DocumentInfo`（`<Dependencies><Value>file:...`）解析出真实
依赖闭包，用它同时过滤 `functions` 与 `funcref_candidates`。

**影响范围**：只挡 `tier100+`（`function.invoke` / `gen.*`）。**不挡 tier0**——Kernel
内建的 20 个 `vibe.*` 操作（`unit.spawn` / `query.units` / `player.set_resource` /
`visual.*` / `upgrade.set_level` / `tech_tree.check` 等）全在 `LibVibeKernel.galaxy` 里，
P1 已证明可用。

### `LibVibeInvokeCommon.galaxy` 的 `StringReplace` 签名错误（open）

Galaxy native 是 `StringReplace(string, string, int start, int end)`——按**下标区间**
替换，不是 JS 式的 find/replace。生成器的 `libVibeInvoke_gf_JsonEscape` 写成了
`StringReplace(s, "\\", "\\\\", true)`，编译器报"参数类型同函数定义不匹配"×5。
需改用 `StringSub` + `StringFind` 手写循环，或确认 `StringReplaceWord` 可用。
同样只挡 tier100+。

## 复现命令

```bash
cd sc2-porting-workspace
PY=C:/Users/22448/.workbuddy/binaries/python/envs/default/Scripts/python.exe
export PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python

# 1. 重新生成句柄表与 invoke 适配器（修 struct 按值传参）
$PY src/projects/cmre-porting/stages/26-full-function-invoke/generate_invoke_adapters.py

# 2. 给地图接 tier0 线
$PY tools/galaxy-vibe/wire_map_includes.py \
    --map "src/projects/cmre-porting/packages/Maps/亡者之夜.SC2Map" --tier tier0

# 3. 静态编译检查
$PY tools/galaxy-vibe/galaxy_compile_check.py \
    --map "src/projects/cmre-porting/packages/Maps/亡者之夜.SC2Map"

# 4. 打包
$PY tools/galaxy-vibe/pack_map_mirror.py \
    --input "src/projects/cmre-porting/packages/Maps/亡者之夜.SC2Map" \
    --out "E:/SC2/SC2new/StarCraft II/Maps/VibeDeadOfNight.SC2Map"

# 5. P0（传输层）
$PY tools/galaxy-vibe/p0_probe_v2.py \
    --map "E:/SC2/SC2new/StarCraft II/Maps/VibeDeadOfNight.SC2Map" --wait 40 --rpc-wait 30

# 6. P1（真改变游戏世界）
$PY tools/galaxy-vibe/p1_probe.py \
    --map "E:/SC2/SC2new/StarCraft II/Maps/VibeDeadOfNight.SC2Map" \
    --unit-type Marine --count 5 --player 1

# 7. 反向对照（必须 FAIL）
$PY tools/galaxy-vibe/p1_probe.py --unit-type ThisUnitDoesNotExistXYZ --count 5 \
    --out artifacts/galaxy-vibe/p1-probe-negative-control.json
```

## 环境注意

- SC2 必须经 `Support64/SC2Switcher_x64.exe -listen 127.0.0.1 -port 5000 -displayMode 0`
  进 API 模式。
- 出现**两个** `SC2_x64` 进程 = 上一轮崩溃留下僵尸，会导致
  `WSMessageTypeError: Received message 257:None`。全杀重启即可。
- `create_game` 之后至少 `sleep(3)` 再 `join_game`，太快会打断 ws（看起来像地图故障，
  实际是竞态）。
- `create_game` 的 `player_setup` 必须是**单** `PlayerSetup(type=1, ...)` + `realtime=True`；
  2 玩家 + `realtime=False` 会直接 `MissingMap`。

## 下一步

1. 修 VIBE-KERNEL-001（悲观响应），消除客户端挂起。
2. 修 GEN-SCOPE-001（按地图依赖闭包过滤）+ `StringReplace` 签名，打开 tier100。
3. tier100 真机验证 `function.invoke` / `gen.*`，进入 P2（`.vtest` 断言脚本）。
