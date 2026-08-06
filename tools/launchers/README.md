# SC2 launcher scripts

本目录只放启动/编排入口。launcher 负责同步 mod、staging 地图、写运行配置、调用 overlay、等待 ready 信号和收集证据；不要在 launcher 里内嵌大段 Galaxy 或 patch 代码。

## 通用规则

- 从仓库根目录运行；优先使用 PowerShell 7：`pwsh -NoProfile -ExecutionPolicy Bypass -File <script> ...`。
- 禁止直接启动 `SC2_x64.exe`；需要真实游戏时走本目录或项目专用 launcher。
- `-DryRun` 只打印/解析依赖；`-NoLaunch` 完成 staging 但不启动游戏。
- 普通/WebUI 启动沿用 CMRE baseline：把 `"<liveMap>"` 作为 `SC2Switcher_x64.exe` 的位置参数；CMRE commander 由 launcher 预设，选择界面已移除。
- 真实启动的轻量地图加载判定：本次 GameLogs 新增 `*Alert*.txt` 表示地图已加载；新增 `*ScriptError*.txt` 表示地图已进入脚本加载但失败。
- API/debug 启动不传 map 给 Switcher；先开 `-listen/-port/-debug`，再由客户端 `CreateGame + JoinGame` 进入地图。
- 改过 `tools/launchers/` 或 `.galaxy` 后，`-NoLaunch` 不算最终验收；必须实际启动游戏、等待 ready，复核本次新增 `*ScriptError*.txt`，并确认 runtime listener/heartbeat。
- GameLogs 默认位置：`$env:USERPROFILE\Documents\StarCraft II\GameLogs`。

## 已验证入口

| 脚本 | 用途 | 推荐命令 | 本次验证 |
| --- | --- | --- | --- |
| `launch-cmre-alenger.ps1` | 当前 CMRE/Alenger/Reborn 主入口；支持 on-demand overlay、API/debug、隔离地图副本。 | `pwsh -NoProfile -ExecutionPolicy Bypass -File .\tools\launchers\launch-cmre-alenger.ps1 -MapName "亡者之夜.SC2Map" -Commander Empire -NoLaunch -MapCopySuffix <suffix>` | PASS：`-DryRun`、`-NoLaunch`、真实启动均 exit 0。 |
| `vibe.ps1` | simulator-first Vibe 入口；不会启动 SC2。 | `pwsh -NoProfile -ExecutionPolicy Bypass -File .\tools\launchers\vibe.ps1 probe` | PASS：`probe` exit 0；`-Backend sc2` 按设计拒绝。 |

## 条件入口 / 当前阻塞

| 脚本 | 预期用途 | 状态 | 使用前处理 |
| --- | --- | --- | --- |
| `launch-cmre-mengsk.ps1` | 旧 Mengsk/标准 commander CMRE 启动入口。 | BLOCKED：当前 dry-run 会找 `..\合作指挥官-起义狂潮\scripts\sc2-launcher\common.ps1`，本机该路径不存在；当前主路径已迁到 `..\cmre-runtime`。 | 若要恢复，先迁移 legacy root/config 路径，或改用 `launch-cmre-alenger.ps1` 的当前 CMRE 入口。 |
| `run-cmre-runtime-baseline.ps1` | 旧 CMRE Mengsk source/generated baseline 验证。 | BLOCKED：`-NoLaunch` source/generated 均阻塞在旧 `..\合作指挥官-起义狂潮` launcher 依赖。 | 恢复前需更新 legacy launcher 依赖和 source/generated 根路径。 |
| `run-live-runtime-probe.ps1` | 无 mod 的 live SC2 API probe。 | PREFLIGHT BLOCKED：默认地图 `artifacts/runtime/cmre/blank_test_neuro.SC2Map` 不存在；脚本会先强制关闭已有 SC2。 | 运行前显式传入存在的 `-Map <path>`，确认可接受关闭已有 SC2，并预期 API 端口可打开。 |

## 常用命令

### CMRE/Alenger staging

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\tools\launchers\launch-cmre-alenger.ps1 `
  -MapName "亡者之夜.SC2Map" `
  -Commander Empire `
  -NoLaunch `
  -MapCopySuffix "dev"
```

### CMRE/Alenger 真实启动

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\tools\launchers\launch-cmre-alenger.ps1 `
  -MapName "亡者之夜.SC2Map" `
  -Commander Empire
```

普通真实启动不要带 `-MapCopySuffix`；本机实测隔离子目录只生成 SystemInfo/Graphics/UI，没有 `Alerts.txt`/runtime listener，无法作为直接进图证据。`-MapCopySuffix` 仍可用于 `-NoLaunch` staging 或 API/debug 路径。

### API / debug 模式

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\tools\launchers\launch-cmre-alenger.ps1 `
  -MapName "亡者之夜.SC2Map" `
  -Commander Empire `
  -ListenPort 5000 `
  -DebugMode `
  -MapCopySuffix "api"
```

### Reborn commander 兼容路径

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\tools\launchers\launch-cmre-alenger.ps1 `
  -MapName "亡者之夜.SC2Map" `
  -Commander ZergZagara `
  -EnableReborn `
  -RebornCommander Zagara `
  -MapCopySuffix "reborn"
```

### Vibe simulator probe

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\tools\launchers\vibe.ps1 probe
```

## 本次验证记录

验证日期：2026-07-31。

- Parser：5/5 scripts PASS。
- `launch-cmre-alenger.ps1 -DryRun`：PASS，打印 CMRE core + Empire on-demand dependency chain。
- `launch-cmre-alenger.ps1 -NoLaunch -MapCopySuffix codex-readme`：PASS，staged 到 SC2 live map copy，并写入 launch profile bank。
- `launch-cmre-alenger.ps1`（无 `-MapCopySuffix`）：PASS，GameLogs 生成 `Alerts.txt`，无新增非空 `*ScriptError*.txt`，runtime listener heartbeat 1→2。
- `launch-cmre-alenger.ps1 -MapCopySuffix <suffix>` 真实普通启动：BLOCKED/拒绝，隔离子目录不产生 `Alerts.txt`/runtime listener；只用于 staging/API。
- `vibe.ps1 probe`：PASS，20 ping / duplicate suppression / illegal rejection / p95 / session recovery / deterministic hash 均通过。
- `launch-cmre-mengsk.ps1`、`run-cmre-runtime-baseline.ps1`：BLOCKED，旧 legacy launcher 路径不存在。
- `run-live-runtime-probe.ps1`：PREFLIGHT BLOCKED，默认 probe map 不存在。
