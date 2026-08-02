# Galaxy Vibe — P0/P1/P2 真机运行指南（所见即所得 vibe 调试）

本目录是 SC2 "所见即所得 vibe" 框架的实现：P0 传输闸门 → P1 最小热循环 REPL → P2 状态断言。
目标：游戏只起一次，敲命令秒级看效果，且能用 `assert` 自动判定 vibe 结果是否正确。

> ⚠️ **必须在能跑 SC2 的真机运行**。本工作环境（沙箱/无头）下 SC2 Switcher 会丢弃
> `-listenPort`，`/sc2api` 起不来（见 `tools/launchers/run-live-runtime-probe.ps1` 注释）。

## 目录内容

| 文件 | 作用 |
|---|---|
| `galaxy-debug-mod/modinfo.xml` | 调试 Mod 描述 |
| `galaxy-debug-mod/Base.SC2Data/LibVibeKernel.galaxy` | 显式 Vibe operation/function.invoke 分发器 + Bank 回传 |
| `transport_probe.py` | SC2API 连接 + 3 探针（MapCommand/Bank/QuickChat）+ `transport-verdict.json` |
| `launch-galaxy-vibe.ps1` | 挂 Mod + 起 API 的启动器（基于现有 launcher 范式） |

## 一次性：编译调试 Mod（编辑器步骤）

1. 用 **Galaxy Editor** 打开 `galaxy-debug-mod` 文件夹（File → Open Mod）。
2. 新建一个 **Map Initialization** 触发器，动作调用 `gf_VibeInit()`。
   （`gf_VibeInit` 会创建 Bank 并注册 Map Command `"dbg"` 处理器。）
3. 保存（Save）。得到可运行的 `.SC2Mod`。

> 函数级调用必须通过 `kernel/function-registry.json` 中的显式 `function_id`；
> 本框架不提供任意 Galaxy 函数反射调用。

## Debug VM：同一游戏窗口反复调函数

Stage 25 增加了一个外部 Debug VM。它热加载 JSON 程序，仍通过现有
`function.invoke` Bank 通道调用 typed registry，因此同一 SC2 会话可以连续执行多组
查询、断言和动作，不需要为每次函数测试重启游戏。

函数发现和函数执行分成两层：

- `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/discovery/function-catalog.json`
  收录 AST 发现的全部函数，包含源文件、行号、签名、分类和效果；当前扫描为
  `35404` 个函数、`0` 个解析错误。
- `kernel/function-registry.json` 只收录有明确参数/返回值/副作用定义和 Galaxy
  handler 的适配器；当前为 `7` 个 function ID（对应 `14` 个头文件/实现声明）。其余
  函数已注册到 inventory catalog，但在适配器完成前不能被 VM 调用。

交互式会话中执行热调试程序：

```powershell
python tools/galaxy-vibe/galaxy_repl.py --port 5152
vibe> vm src/projects/cmre-porting/stages/25-ai-ally-capability-completion/debug-vm-smoke.json
vibe> vm another-program.json
```

同一个 REPL 进程内会连续复用 Kernel session。若需要从另一个 REPL 进程接续，使用
上一次成功 response 中的 `session_id`：

```powershell
python tools/galaxy-vibe/galaxy_repl.py --port 5152 --rpc-session-id repl_<existing-session>
```

不要在同一游戏里随机生成新的 session 后直接调用；Kernel 会拒绝跨 session 请求，
这是会话隔离，不是游戏需要重启。

也可以一次执行后返回结果码：

```powershell
python tools/galaxy-vibe/galaxy_repl.py --port 5152 `
  --vm-program src/projects/cmre-porting/stages/25-ai-ally-capability-completion/debug-vm-smoke.json
```

程序格式固定为 `vibe-debug/1`，支持 `call`、`step`、`assert`、`set`、`repeat` 和
`catalog.search`。`mode: "strategy"` 会拒绝 `debug_only` 函数，例如刷兵、改资源和
强制击杀；`debug` 模式也只能调用 registry 中的显式 ID，不会执行 `eval` 或任意
Galaxy 函数名。

重新生成完整目录时，只读扫描两个已注册源：

```powershell
node src/projects/cmre-porting/stages/25-ai-ally-capability-completion/discover_function_catalog.mjs `
  --out artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/discovery/function-catalog.json `
  --source cmre-dev-package=<registered-CMRE-package-root> `
  --source cmre-owned-project=src/projects/cmre-porting/packages
```

新增可运行函数时，先在 registry 增加 typed schema，再在 Host、Galaxy Kernel 和
simulator 各自的显式 dispatch map 增加同名适配器；只把稳定、可验证的函数提升为
callable，等待适配器的内部函数继续保留在 catalog 中供搜索和定位。

## 运行 P0 闸门

任选其一：

**A. 一键启动 + 自动跑探针**
```powershell
cd E:\Code\sc2-porting-workspace
powershell -File tools/galaxy-vibe/launch-galaxy-vibe.ps1 -AutoProbe
```

**B. 分开跑（先看游戏起来）**
```powershell
# 终端 1：启动 SC2 + Mod + API
powershell -File tools/galaxy-vibe/launch-galaxy-vibe.ps1

# 终端 2：跑传输探针
python tools/galaxy-vibe/transport_probe.py --port 5000
```

## 判定 P0 通过

探针输出 `artifacts/galaxy-vibe/transport-verdict.json`：

- `verdict.connect == true`（SC2API 连通）
- `probes.mapcommand_bank.all_ack == true`（20 次 `dbg ping` 全部 ack 且 bank `result=="pong"`）
- `probes.mapcommand_bank.idempotent_ok == runs`（重发同 run_id 一致、不崩）
- `probes.illegal_request.handled_without_crash == true`（`dbg bogus` 优雅处理）
- `probes.mapcommand_bank.p95_latency_s <= 2.0`

并手动确认：本次启动在
`%USERPROFILE%\Documents\StarCraft II\GameLogs\` **无新增 `ScriptError.*.txt`**。

全部满足 → P0 通过，进 P1。

## P1 最小热循环（Vibe REPL）

`galaxy_repl.py` 是交互式 vibe 调试台：**游戏只起一次，敲命令秒级看效果，无需重编译/重开。**

### 设计要点（与最初计划的两处修正）

- **`spawn` / `kill` / `set` / `cheat` / `query` / `obs` / `info` / `step` 全部走 SC2API 已验证接口**
  （`RequestDebug` / `RequestObservation` / `RequestGameInfo` / `RequestStep`），**不依赖任何未验证的 Galaxy native**。
  证据：字段名取自 vendored `python-sc2/client.py` 与 `debug_pb2` 描述符文本（`static` 已核对）。
- **`invoke` / `ping` / `echo` 走正式 Vibe Map Command/Bank 分发器**（P0 已落地）。
- 本 vendored `debug_pb2` 版本**没有 `DebugSetPlayerState`**（只有 `game_state` 作弊枚举
  minerals/gas/god）。精确设置玩家资源应注册一个 typed Vibe function，
  再通过 `invoke <function_id> key=value` 调用，避免任意函数反射。
  REPL 不内置该字段，避免猜签名。

### 启动 + 进 REPL（推荐）

```powershell
cd E:\Code\sc2-porting-workspace
powershell -File tools/galaxy-vibe/launch-galaxy-vibe.ps1 -Repl
```

游戏起来后自动进入 `vibe>` 交互提示符。

### 单独进 REPL

```powershell
# 游戏已在运行（无论是否用本启动器）
python tools/galaxy-vibe/galaxy_repl.py --port 5000
```

### REPL 命令

| 命令 | 作用 |
|---|---|
| `ping` | 验证 Mod 闭环（下发 `dbg ping` + 读 Bank） |
| `invoke <function_id> [key=value ...]` | 调用显式注册的 typed Vibe function |
| `echo <text>` | 回显文本到 Bank |
| `spawn <type> <count> [player] [@x,y]` | 秒级刷兵（type 用英文名或整数 id；默认落地图中心） |
| `kill <all\|player N\|tag t1 t2...>` | 击杀单位 |
| `set <hp\|energy\|shields> <val> <player N\|tag ...>` | 设单位属性 |
| `cheat <minerals\|gas\|god> <on\|off>` | 资源/上帝模式作弊 |
| `query [player N]` | 汇总单位与资源 |
| `obs` | 观察原始摘要 |
| `info` | 地图/玩家信息 |
| `step [n]` | 推进 n 帧 |
| `help` / `exit` | 帮助 / 退出 |

非交互：`python galaxy_repl.py --cmd "spawn marine 5 1"` 或 `--script cmds.txt`（每行一条，# 注释）。

### 典型 vibe 节奏

```
vibe> spawn marine 5 1          # 玩家1 刷 5 个兵
vibe> query 1                   # 看玩家1 单位
vibe> invoke vibe.test.ping nonce=stage16  # 调用显式注册函数
vibe> query 1                   # 对比前后状态
vibe> set shields 50 player 1   # 把玩家1 所有单位护盾设 50
vibe> kill all                  # 清场重来
```

> 只有当你要测**全新逻辑**时才改 Galaxy/Mod 重编译一次；之后用 registry 中的 typed function 循环压到秒级。

## P2 状态断言（自动判定，告别肉眼看）

`assert` 命令让 vibe 从"肉眼看"进化到"自动判定"——给定玩家快照，自动判定某个条件是否成立，
结果打印 `PASS/FAIL` 并落盘 `artifacts/galaxy-vibe/assert-results.json`（供冷循环/CI 读取）。

### assert 命令

| 命令 | 含义 | 示例 |
|---|---|---|
| `assert exists <unit> [--player N]` | 玩家场上至少有 1 个该单位 | `assert exists marine --player 1` |
| `assert not_exists <unit> [--player N]` | 玩家场上该单位数为 0 | `assert not_exists marine --player 2` |
| `assert count <unit> <cmp> <N> [--player N]` | 数量比较（`== >= > <= <`） | `assert count marine == 5 --player 1` |
| `assert range <unit> <min> <max> [--player N]` | 数量在区间 [min,max] | `assert range marine 3 6 --player 1` |
| `assert eventually <op> ... [--within S]` | 轮询直到满足或超时（默认 5s） | `assert eventually exists marine --player 1 --within 3` |

默认玩家 = 1；`<unit>` 可用 python-sc2 英文名（权威 id 来自 vendored 源码，marine=48）或整数 id。
`eventually` 会每 0.25s 轮询快照，直到条件满足或 `--within S` 秒超时。

### 确定性 scenario（批量自动验收）

把 spawn/invoke/assert 串进一个 `.vtest` 文本文件，用 `--assert-file` 跑：

```text
# my_test.vtest —— 一个确定性 scenario
spawn marine 5 1
assert count marine == 5 --player 1
invoke vibe.test.ping nonce=stage16
assert exists zealot --player 1
assert eventually not_exists marine --player 1 --within 10
```

```powershell
python tools/galaxy-vibe/galaxy_repl.py --assert-file my_test.vtest
```

结束打印 `PASS x/N` 汇总；**全部通过退出码 0，否则退出码 1**（可直接接 CI / 冷循环门禁）。

### P2 验收（真机）

- `spawn marine 5 1` → `assert count marine == 5 --player 1` → **PASS**；
- `assert not_exists marine --player 2`（空场）→ **PASS**；
- `assert count marine == 99 --player 1` → **FAIL**（正确暴露差异）；
- `assert eventually exists marine --player 1 --within 3` 在刷兵后 **PASS**；
- 本次启动 `GameLogs` 无新增 `ScriptError.*.txt`。

## 验收闸门自动化（ScriptError 复核）

P0/P1/P2 的「通过」硬条件之一都是"本次启动无新增 `ScriptError.*.txt`"。原靠人工翻 GameLogs，
现用 `script_error_check.py` 自动判定：

```powershell
# 读 launcher 写的启动标记，判定本次启动以来是否有新增 ScriptError（推荐）
python tools/galaxy-vibe/script_error_check.py
# 或显式给定启动时间（epoch 秒）
python tools/galaxy-vibe/script_error_check.py --since 1785367253
```

- 输出 `artifacts/galaxy-vibe/script-error-verdict.json`：`{has_new_errors, count, files[], ...}`。
- 退出码：**无新增 = 0（闸门通过）；有新增 = 1（闸门失败）**，可直接接 CI / 冷循环门禁。
- `launch-galaxy-vibe.ps1` 在游戏就绪后会写 `Documents/StarCraft II/galaxy-vibe-launch.json`
  （含 `launched_at`），复核器默认读它，无需手填时间。

> 这是计划里 P4 冷循环的 ScriptError 复核子项，**提前实现**——它直接服务 P0/P1/P2 的通过判定，
> 且能离线验证。P3 视觉闭环（固定镜头/分辨率/稳定帧截图 + ROI 差异）依赖真机游戏窗口截图，
> 沙箱无法验证，推后到真机阶段。

### 一键验收（-Verify）

把「启动 → 跑 scenario → 查崩溃闸门 → 汇总」串成真机一条命令，最终输出 `vibe-verdict.json` + 退出码：

```powershell
cd E:\Code\sc2-porting-workspace
powershell -File tools/galaxy-vibe/launch-galaxy-vibe.ps1 -Verify tools/galaxy-vibe/examples/my_test.vtest
```

流程：launcher 写启动 marker → REPL 跑 `--assert-file` 写 `assert-results.json` →
`script_error_check.py` 写 `script-error-verdict.json` → `summarize_verdict.py` 读两者合成
`vibe-verdict.json`，**全过退出码 0、否则 1**。这把 P0/P1/P2 的验收收口成一次命令。

（也可分步手动：先 `-Repl` 交互，退出后单独跑 `script_error_check.py` 与 `summarize_verdict.py`。）

> 仓库已附示例模板 `tools/galaxy-vibe/examples/my_test.vtest`：spawn→assert→invoke→assert 标准节奏，
> 其中纯 SC2API 断言（spawn / count / exists / range / eventually）不依赖自定义 Galaxy 函数，
> 可直接拿来跑；新增函数必须先登记到 `kernel/function-registry.json`。

## P4 冷循环（变更感知 + 场景重建）

改了 Galaxy/XML 后，自动判断是否需要重编译、并重建干净场景重新验收。`cold_cycle.py` 负责
「变更分类」与「场景重建脚本生成」（离线可验）；**重编译 Galaxy 仍需在 Galaxy Editor 保存**
（冷循环不能自动编译）。

```powershell
# 1) 首次打快照；之后每次改源码后检查变更
python tools/galaxy-vibe/cold_cycle.py --snapshot tools/galaxy-vibe/galaxy-debug-mod
python tools/galaxy-vibe/cold_cycle.py --check   tools/galaxy-vibe/galaxy-debug-mod
#    -> 有变更则提示：去 Galaxy Editor 重存 Mod（重编译）

# 2) 生成场景重建脚本（清场 + 复位资源）
python tools/galaxy-vibe/cold_cycle.py --emit-reset

# 3) 用重建脚本跑验收（重建 + 复核闸门）
powershell -File tools/galaxy-vibe/launch-galaxy-vibe.ps1 -Verify artifacts/galaxy-vibe/reset.vtest
```

- `--snapshot <MOD_DIR>` 对 `.galaxy/.xml` 递归算 sha256 指纹并存储；
- `--check <MOD_DIR>` 比对，输出 `{changed, added, modified, deleted}`，退出码 changed?1:0；
- `--emit-reset` 生成 `reset.vtest`（`kill all` + `cheat minerals/gas on`），使 scenario 从干净状态开始。

> P3 视觉闭环算法（ROI 差异 + 采集适配器）已离线可验（见下节）；仅「实时窗口采集」依赖真机 mss，
> 沙箱自动跳过，推后到真机阶段。

## P3 视觉闭环（ROI 差异 + 采集适配器）

`visual_loop.py` 把"肉眼看画面"升级成"像素级自动判定"——给定两帧（或连续采集）算 ROI 内平均像素差，
按阈值判定"变了 / 稳了"。算法部分纯图像数学，**离线可验**；实时窗口采集（mss）依赖真机，沙箱跳过。

### 命令
| 命令 | 作用 |
|---|---|
| `--diff A.png B.png [--roi x,y,w,h] [--threshold N]` | 比两图，输出 `{mean_diff, changed}`；changed 退出码 1，否则 0 |
| `--selftest DIR` | 生成合成测试图 + 断言 diff 行为（4 用例），退出码 0/1 |
| `--capture-loop --adapter file\|mss [--src DIR] [--frames N] [--steady K] [--roi ...] [--threshold N]` | 连续采集判定场景稳定，写 `visual-verdict.json`（`stable`/`visual_passed`） |

- `FileCaptureAdapter`：从历史截图目录回放，离线验证 / 真机回放都能用；
- `MssCaptureAdapter`：真机抓游戏窗口（需 `pip install mss`，游戏以窗口模式跑），沙箱无 mss 自动跳过、不写 verdict（避免假通过）。

### 接入一键验收
`launch-galaxy-vibe.ps1 -Verify <scenario> -Visual [-VisualRoi "x,y,w,h" [-VisualThreshold 8] [-VisualSteady 3]]`：
在 assert + ScriptError 闸门之后追加 `visual_loop --adapter mss`，把 `visual-verdict.json` 一并收口进
`vibe-verdict.json`（视觉不稳 → 最终 FAIL）。无 `-Visual` 时不影响既有链路。

### 验证（已执行）
`py_compile` 通过；`--selftest` 4 用例全过（相同图不变；ROI 改动变；ROI 外不变；全图变）；
`--diff` base/same→mean_diff 0/exit0，base/roi_changed@roi→24/exit1；`--capture-loop` file 适配器稳态序列
steady=3/3→stable=true/exit0；`summarize_verdict.py` 接入 visual-verdict（pass→PASS、fail→FAIL、缺省不影响）；
mss 适配器沙箱跳过 exit0 且不写 verdict。P3 实时采集判定属 visual 证据，待 master 真机桌面跑 `-Visual` 成立。

## 排错

- **API 端口没起来**：真机上也起不来时，检查 SC2 是否以 Switcher 正常启动、GameLogs 有无报错；
  沙箱环境本就不支持。
- **Bank 始终读不到**：确认 Mod 已编译（含 `gf_VibeInit` 触发器）、游戏确实进入了可操作状态、
  `Documents/StarCraft II/Banks/GalaxyVibeDebug.SC2Bank` 是否被生成。
- **`dbg` 无响应**：确认 Map Command 事件处理器已在 `gf_VibeInit` 内注册（编辑器里触发器确实保存）。
