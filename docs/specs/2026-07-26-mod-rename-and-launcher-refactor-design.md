# Mod 重命名 + 目录迁移 + Launcher 启动模式区分设计

日期：2026-07-26
状态：待用户审阅

## 背景

当前 CMRE 移植项目的起义指挥官 mod 存在三个问题：

1. **mod 命名不直观**：12 个起义指挥官 mod 都叫 `AlengerN.SC2Mod`（如 Alenger3），从目录名看不出对应哪个指挥官。
2. **目录关联错误**：mod 放在 `packages/Mods/7vs1/` 下，但这些 mod 与"7vs1 起义狂潮"原项目无关联，目录名有误导性。
3. **启动模式未区分**：WebUI 玩家启动和 AI 调试启动共用同一套启动逻辑，PowerShell 控制台窗口会弹出干扰用户，调试模式也没有独立的窗口/进程管理。

本设计通过三项改造解决上述问题：(A) mod 重命名为语义化英文名；(B) 目录从 `7vs1/` 迁移到 `Commanders/`；(C) launcher 新增 `-PlayerMode` / `-DebugMode` 参数区分场景。

## 一、英文名对照表

所有起义指挥官 mod 目录名加 `Alenger` 后缀，与其他 mod（CMRE / reborn / 官方指挥官）区分。

| 旧 ID | 中文名 | 新英文名（ID） | mod 目录 | Adapter 目录 |
|-------|--------|----------------|----------|--------------|
| Alenger1 | 钢铁长城 | SteelWall | SteelWallAlenger.SC2Mod | SteelWallAlengerAdapter.SC2Mod |
| Alenger2 | 贝希摩斯 | Behemoth | BehemothAlenger.SC2Mod | BehemothAlengerAdapter.SC2Mod |
| Alenger3 | 疯批帝国 | Empire | EmpireAlenger.SC2Mod | EmpireAlengerAdapter.SC2Mod |
| Alenger4 | 塔达林 | TalDarim | TalDarimAlenger.SC2Mod | TalDarimAlengerAdapter.SC2Mod |
| Alenger6 | 阿巴瑟 | Abathur | AbathurAlenger.SC2Mod | AbathurAlengerAdapter.SC2Mod |
| Alenger7 | 卡莱 | Khalai | KhalaiAlenger.SC2Mod | KhalaiAlengerAdapter.SC2Mod |
| Alenger8 | 扎加拉 | Zagara | ZagaraAlenger.SC2Mod | ZagaraAlengerAdapter.SC2Mod |
| Alenger9 | 海盗 | Pirate | PirateAlenger.SC2Mod | PirateAlengerAdapter.SC2Mod |
| Alenger10 | 埃蒙 | Amon | AmonAlenger.SC2Mod | AmonAlengerAdapter.SC2Mod |
| Alenger11 | 群友 | Community | CommunityAlenger.SC2Mod | CommunityAlengerAdapter.SC2Mod |
| Alenger12 | 游骑兵 | Ranger | RangerAlenger.SC2Mod | RangerAlengerAdapter.SC2Mod |
| Alenger13 | 净化者 | Purifier | PurifierAlenger.SC2Mod | PurifierAlengerAdapter.SC2Mod |

Common mod 重命名：
- `AlengerCommon.SC2Mod`（仅 Empire 用）→ `EmpireAlengerCommon.SC2Mod`
- `Alenger6Common.SC2Mod`（其余 11 个用）→ `SharedAlengerCommon.SC2Mod`

其他 mod（CoreRuntime / CommanderBridge / BaseCatalogPatch / ExternalRefs / SharedUnits / CommanderUnits_Swann / CommanderUnits_Dehaka）保持原名，仅迁移目录。

### 标识符彻底改用英文名

- `-Commander` 参数用英文名（如 `-Commander Empire`），不再接受 `Alenger3`
- `commanderToAlenger` 和 `commanderProfiles` 的 key 改为英文名
- launcher 正则匹配改为枚举英文名

### 保持不变的部分

- **galaxy 库前缀**（A1ADAPTER, A2ADAPTER 等）：mod 内部编译产物，改名风险大
- **adapterFiles**（LibA1ADAPTER.galaxy 等）：同上
- **adapterModName**（Alenger1Adapter 等）：galaxy 库引用名，保持

## 二、目录结构变化

```
packages/Mods/
├── CMRE/                  (不变)
├── reborn/                (不变)
└── Commanders/            (新，替代旧 7vs1/)
    ├── SteelWallAlenger.SC2Mod
    ├── SteelWallAlengerAdapter.SC2Mod
    ├── BehemothAlenger.SC2Mod
    ├── BehemothAlengerAdapter.SC2Mod
    ├── EmpireAlenger.SC2Mod
    ├── EmpireAlengerAdapter.SC2Mod
    ├── TalDarimAlenger.SC2Mod
    ├── ...
    ├── EmpireAlengerCommon.SC2Mod
    ├── SharedAlengerCommon.SC2Mod
    ├── CoreRuntime.SC2Mod
    ├── CommanderBridge.SC2Mod
    ├── BaseCatalogPatch.SC2Mod
    ├── ExternalRefs.SC2Mod
    ├── SharedUnits.SC2Mod
    ├── CommanderUnits_Swann.SC2Mod
    └── CommanderUnits_Dehaka.SC2Mod
```

执行方式：`git mv` 保留历史（33 个 mod 逐一迁移）。

## 三、配置文件改动

### alenger-mods.json

- `commanderToAlenger` 的 key：`Alenger1` → `SteelWall`，`Alenger3` → `Empire`，...
- `commanderToAlenger` 的 value：mod 名同步改（`Alenger1` → `SteelWall`，`Alenger1Adapter` → `SteelWallAdapter`，`Alenger6Common` → `SharedCommon`，`AlengerCommon` → `EmpireCommon`）
- `commanderProfiles` 的 key：同步改为英文名
- `commanderProfiles` 内部字段（adapterModName / adapterLibPrefix / adapterFiles）：保持不变
- `workerCount`：全部统一为 12（已在前置任务中完成）

### cmre-alenger-dependencies.json

- 当前未引用 `Mods/7vs1/` 路径，无需改动
- `extraPackageMods` 中的 `Alenger\通用效果.SC2Mod` 是包内相对路径，保持不变

## 四、launcher 改动（launch-cmre-alenger.ps1）

### 4.1 新增启动模式参数

新增两个互斥开关：

| 参数 | 场景 | PS 控制台 | SC2 游戏窗口 | -ApiMinimal | -ListenPort | SC2 退出策略 |
|------|------|-----------|--------------|-------------|-------------|--------------|
| `-PlayerMode` | WebUI 玩家启动 | 隐藏 (CREATE_NO_WINDOW) | 正常显示 | 不传 | 不传 | 不主动关闭 |
| `-DebugMode` | AI 调试脚本 | 隐藏 (CREATE_NO_WINDOW) | 最小化（Win32 API） | 自动传 | 必填 | launcher 退出时自动关闭 SC2 |
| (都不传) | 命令行手动启动 | 显示 | 显示 | 看其他参数 | 看其他参数 | 不主动关闭 |

- `-DebugMode` 内部自动设 `$ApiMinimal = $true`，并要求 `-ListenPort > 0`
- `-PlayerMode` 和 `-DebugMode` 互斥，同时传报错

### 4.2 路径和正则改动

- mod 路径：`Mods/7vs1/$_.SC2Mod` → `Mods/Commanders/$_.SC2Mod`
- 正则匹配：`^(Terran|Zerg|Protoss)?(Alenger\d+)$` → `^(Terran|Zerg|Protoss)?(SteelWall|Behemoth|Empire|TalDarim|Abathur|Khalai|Zagara|Pirate|Amon|Community|Ranger|Purifier)$`

### 4.3 调试模式窗口最小化

启动 SC2_x64 后，用 Win32 API `ShowWindowAsync` 强制最小化 SC2 窗口：

```powershell
# 加载 Win32 API
$signature = @"
[DllImport("user32.dll")]
public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);
"@
$type = Add-Type -MemberDefinition $signature -Name "Win32ShowWindowAsync" -Namespace Win32Functions -PassThru
# SW_MINIMIZE = 6
$sc2Proc = Get-Process -Name "SC2_x64" -ErrorAction SilentlyContinue
if ($sc2Proc) { $type::ShowWindowAsync($sc2Proc.MainWindowHandle, 6) | Out-Null }
```

### 4.4 调试模式自动关闭 SC2

launcher 退出时（调试模式），用 `try/finally` 关闭本 launcher 启动的 SC2 进程（按 PID，不按进程名，详见 4.5）：

```powershell
try {
    # ... 主逻辑 ...
} finally {
    if ($DebugMode -and (Test-Path $debugPidFile)) {
        $pid = Get-Content $debugPidFile
        if ($pid) { Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue }
        Remove-Item $debugPidFile -Force -ErrorAction SilentlyContinue
    }
}
```

### 4.5 启动前进程清理的隔离（关键安全点）

**当前问题**：launcher 第 950-954 行无条件调用 `Stop-RunningSc2` + `Get-Process SC2","StarCraft II" | Stop-Process`，会杀掉所有 SC2 进程，包括玩家正在玩的游戏。

**隔离方案**：区分 PlayerMode 和 DebugMode 的清理策略。

| 模式 | 启动前清理 | 退出时清理 |
|------|-----------|-----------|
| `-PlayerMode` | **不清理**任何 SC2 进程（避免杀玩家游戏）。仅 Acquire-TestLock 防止 WebUI 并发启动。如果已有 SC2 进程在跑，报错退出提示用户。 | 不主动关闭 SC2（让玩家自己关） |
| `-DebugMode` | **只清理 DebugMode 自己启动的 SC2 进程**。用 PID 文件记录调试模式启动的 SC2_x64 PID，下次启动前只 kill 这个 PID。 | 关闭调试模式自己启动的 SC2 进程（按 PID 文件，不按进程名） |
| (都不传) | 走原有 `Stop-RunningSc2` 逻辑（命令行手动启动默认假设独占）。 | 不主动关闭 |

**PID 文件方案**：

```powershell
# 调试模式 PID 文件路径
$debugPidFile = Join-Path $env:TEMP "cmre-debug-sc2.pid"

# DebugMode 启动 SC2 后记录 PID
$sc2Proc = Get-Process -Name "SC2_x64" -ErrorAction SilentlyContinue
if ($sc2Proc) { Set-Content -Path $debugPidFile -Value $sc2Proc.Id }

# DebugMode 启动前清理：只 kill PID 文件记录的进程
if (Test-Path $debugPidFile) {
    $oldPid = Get-Content $debugPidFile
    if ($oldPid) {
        Stop-Process -Id $oldPid -Force -ErrorAction SilentlyContinue
    }
    Remove-Item $debugPidFile -Force -ErrorAction SilentlyContinue
}

# DebugMode 退出时清理（finally 块）
if ($DebugMode -and (Test-Path $debugPidFile)) {
    $pid = Get-Content $debugPidFile
    if ($pid) { Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue }
    Remove-Item $debugPidFile -Force -ErrorAction SilentlyContinue
}
```

**PlayerMode 启动前检查**：

```powershell
if ($PlayerMode) {
    $existing = Get-Process -Name "SC2_x64","SC2","StarCraft II" -ErrorAction SilentlyContinue
    if ($existing) {
        throw "检测到 SC2 已在运行（PID: $($existing.Id -join ',')）。PlayerMode 不会自动关闭已有游戏，请先手动关闭 SC2 再启动。"
    }
}
```

**关键约束**：
- DebugMode 的 `Stop-Process` 一律按 PID，**禁止** `Stop-Process -Name SC2_x64`（会误杀玩家游戏）
- 原有 `Stop-RunningSc2` 函数只在"都不传"模式（命令行手动启动）下使用
- Clear-GameLogs 也只在确认无 SC2 进程时执行（避免删锁文件）

## 五、WebUI 改动

### 5.1 server.py

- `subprocess.Popen` 加 `creationflags=subprocess.CREATE_NO_WINDOW`（Windows 常量，隐藏 PS 控制台窗口）
- WebUI 默认启动传 `-PlayerMode`
- WebUI 勾选"SC2API 校准模式"时传 `-DebugMode -ListenPort <port>`（不再直接传 -ApiMinimal）

### 5.2 前端（app.js / index.html）

- "SC2API 校准模式"复选框逻辑不变，后端转换为 `-DebugMode`

## 六、AI 调试脚本改动

- `run-cmre-sc2api.ps1` 等调试入口改为传 `-DebugMode -ListenPort <port>`
- 不再直接传 `-ApiMinimal`（由 `-DebugMode` 内部自动设）

## 七、风险与测试方案

### 风险

1. **galaxy 库前缀保持不变**：A1ADAPTER 等是 mod 编译时生成的库引用名，与 mod 目录名无关。保持不变可避免 mod 内部 galaxy 代码重新编译。
2. **bank key / commander power metadata 引用**：需在实施时排查是否有地方引用 `AlengerN` 字符串，同步改为英文名。
3. **SC2 游戏窗口最小化**：`ShowWindowAsync` 对 SC2_x64 可能不立即生效（SC2 启动时窗口创建有延迟），需轮询重试。
4. **CREATE_NO_WINDOW**：Python 3.7+ 支持，需确认 server.py 的 Python 版本。

### 测试方案

1. **DryRun 验证**：`launch-cmre-alenger.ps1 -Commander Empire -DryRun` 确认配置正确加载
2. **玩家模式测试**：WebUI 启动 Empire + 亡者之夜，确认：
   - PS 控制台不弹出
   - SC2 游戏窗口正常显示
   - 开局 12 个农民
   - 无 ScriptError
3. **调试模式测试**：`launch-cmre-alenger.ps1 -Commander Empire -DebugMode -ListenPort 5000`，确认：
   - PS 控制台不弹出
   - SC2 游戏窗口最小化
   - API 端口可连接
   - launcher 退出后 SC2 自动关闭

## 八、实施顺序

1. mod 目录迁移（git mv）+ Common mod 重命名
2. alenger-mods.json 配置更新（key/value 改英文名）
3. launch-cmre-alenger.ps1 改动（路径/正则/新参数/窗口最小化/自动关闭）
4. server.py 改动（CREATE_NO_WINDOW + -PlayerMode/-DebugMode）
5. AI 调试脚本改动
6. DryRun 验证
7. 玩家模式进图测试
8. 调试模式测试
9. git commit + push
