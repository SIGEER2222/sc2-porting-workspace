# Mod 重命名 + 目录迁移 + Launcher 启动模式区分 实施计划

> **For agentic workers:** 本计划按任务顺序执行，每个任务有明确的文件路径和验证步骤。SC2 mod 项目无标准单元测试，验证方式为 DryRun + 进图测试 + GameLogs 复核。

**Goal:** 将起义指挥官 mod 从 `Mods/7vs1/AlengerN.SC2Mod` 重命名为 `Mods/Commanders/<EnglishName>Alenger.SC2Mod`，并给 launcher 加 `-PlayerMode` / `-DebugMode` 区分玩家和 AI 调试，确保 AI 调试不会杀掉玩家游戏。

**Architecture:** (1) git mv 迁移 33 个 mod 目录并重命名；(2) 同步更新 alenger-mods.json 配置 key/value；(3) launcher 改正则 + 路径 + 新增模式参数 + PID 文件隔离；(4) server.py 加 CREATE_NO_WINDOW + 转发模式参数。

**Tech Stack:** PowerShell 5.x (launcher)、Python stdlib (WebUI server)、SC2 mod XML、Git。

**前置条件:**
- 已完成 alenger-mods.json 的 workerCount 统一为 12（前置任务）
- 设计文档：`docs/specs/2026-07-26-mod-rename-and-launcher-refactor-design.md`
- 工作区干净（除已修改的 alenger-mods.json 和 launch-cmre-alenger.ps1）

---

## 任务 1：用脚本批量 git mv 迁移并重命名 mod 目录

**Files:**
- 移动: `packages/Mods/7vs1/*.SC2Mod` → `packages/Mods/Commanders/*.SC2Mod`（33 个 mod，含重命名）
- 创建: `%TEMP%\migrate-mods.ps1`（一次性迁移脚本，用完删除）

**迁移映射表（旧名 → 新名）：**

指挥官 mod（12 个）：
- Alenger1.SC2Mod → SteelWallAlenger.SC2Mod
- Alenger2.SC2Mod → BehemothAlenger.SC2Mod
- Alenger3.SC2Mod → EmpireAlenger.SC2Mod
- Alenger4.SC2Mod → TalDarimAlenger.SC2Mod
- Alenger6.SC2Mod → AbathurAlenger.SC2Mod
- Alenger7.SC2Mod → KhalaiAlenger.SC2Mod
- Alenger8.SC2Mod → ZagaraAlenger.SC2Mod
- Alenger9.SC2Mod → PirateAlenger.SC2Mod
- Alenger10.SC2Mod → AmonAlenger.SC2Mod
- Alenger11.SC2Mod → CommunityAlenger.SC2Mod
- Alenger12.SC2Mod → RangerAlenger.SC2Mod
- Alenger13.SC2Mod → PurifierAlenger.SC2Mod

Adapter mod（12 个）：
- Alenger1Adapter.SC2Mod → SteelWallAlengerAdapter.SC2Mod
- Alenger2Adapter.SC2Mod → BehemothAlengerAdapter.SC2Mod
- Alenger3Adapter.SC2Mod → EmpireAlengerAdapter.SC2Mod
- Alenger4Adapter.SC2Mod → TalDarimAlengerAdapter.SC2Mod
- Alenger6Adapter.SC2Mod → AbathurAlengerAdapter.SC2Mod
- Alenger7Adapter.SC2Mod → KhalaiAlengerAdapter.SC2Mod
- Alenger8Adapter.SC2Mod → ZagaraAlengerAdapter.SC2Mod
- Alenger9Adapter.SC2Mod → PirateAlengerAdapter.SC2Mod
- Alenger10Adapter.SC2Mod → AmonAlengerAdapter.SC2Mod
- Alenger11Adapter.SC2Mod → CommunityAlengerAdapter.SC2Mod
- Alenger12Adapter.SC2Mod → RangerAlengerAdapter.SC2Mod
- Alenger13Adapter.SC2Mod → PurifierAlengerAdapter.SC2Mod

Common mod（2 个，重命名）：
- AlengerCommon.SC2Mod → EmpireAlengerCommon.SC2Mod
- Alenger6Common.SC2Mod → SharedAlengerCommon.SC2Mod

其他 mod（7 个，仅迁移不重命名）：
- CoreRuntime.SC2Mod、CommanderBridge.SC2Mod、BaseCatalogPatch.SC2Mod、ExternalRefs.SC2Mod、SharedUnits.SC2Mod、CommanderUnits_Swann.SC2Mod、CommanderUnits_Dehaka.SC2Mod

- [ ] **Step 1: 创建目标目录**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-mkdir.ps1" "e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\src\projects\cmre-porting\packages\Mods\Commanders"
```

- [ ] **Step 2: 写迁移脚本到 %TEMP%**

迁移脚本内容（写到 `$env:TEMP\migrate-mods.ps1`，脚本内部只调用 `git mv`，不调用原生 Move-Item）：

```powershell
$src = "e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\src\projects\cmre-porting\packages\Mods\7vs1"
$dst = "e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\src\projects\cmre-porting\packages\Mods\Commanders"

# 映射表：旧名 → 新名
$map = @{
    "Alenger1"  = "SteelWallAlenger"
    "Alenger2"  = "BehemothAlenger"
    "Alenger3"  = "EmpireAlenger"
    "Alenger4"  = "TalDarimAlenger"
    "Alenger6"  = "AbathurAlenger"
    "Alenger7"  = "KhalaiAlenger"
    "Alenger8"  = "ZagaraAlenger"
    "Alenger9"  = "PirateAlenger"
    "Alenger10" = "AmonAlenger"
    "Alenger11" = "CommunityAlenger"
    "Alenger12" = "RangerAlenger"
    "Alenger13" = "PurifierAlenger"
    "AlengerCommon"  = "EmpireAlengerCommon"
    "Alenger6Common" = "SharedAlengerCommon"
}

# 指挥官 mod + Adapter + Common（带重命名）
foreach ($k in $map.Keys) {
    foreach ($suffix in @(".SC2Mod", "Adapter.SC2Mod")) {
        $oldDir = Join-Path $src "$k$suffix"
        if (-not (Test-Path -LiteralPath $oldDir)) { continue }
        # Adapter 的目录名是 AlengerNAdapter.SC2Mod，对应新名是 <Eng>AlengerAdapter.SC2Mod
        if ($suffix -eq "Adapter.SC2Mod") {
            $newName = $map[$k] + "Adapter.SC2Mod"
        } else {
            $newName = $map[$k] + ".SC2Mod"
        }
        $newDir = Join-Path $dst $newName
        Write-Host "git mv `"$oldDir`" `"$newDir`""
        & git mv "$oldDir" "$newDir"
        if ($LASTEXITCODE -ne 0) { throw "git mv failed: $oldDir -> $newDir" }
    }
}

# 其他 mod（仅迁移不重命名）
$others = @("CoreRuntime","CommanderBridge","BaseCatalogPatch","ExternalRefs","SharedUnits","CommanderUnits_Swann","CommanderUnits_Dehaka")
foreach ($name in $others) {
    $oldDir = Join-Path $src "$name.SC2Mod"
    if (-not (Test-Path -LiteralPath $oldDir)) { continue }
    $newDir = Join-Path $dst "$name.SC2Mod"
    Write-Host "git mv `"$oldDir`" `"$newDir`""
    & git mv "$oldDir" "$newDir"
    if ($LASTEXITCODE -ne 0) { throw "git mv failed: $oldDir -> $newDir" }
}

Write-Host "Migration done."
```

- [ ] **Step 3: 执行迁移脚本**

```powershell
cd e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace
powershell -NoProfile -ExecutionPolicy Bypass -File "$env:TEMP\migrate-mods.ps1"
```

- [ ] **Step 4: 验证迁移结果**

```powershell
# 旧目录应为空或不存在
ls e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\src\projects\cmre-porting\packages\Mods\7vs1\
# 新目录应有 33 个 .SC2Mod
ls e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\src\projects\cmre-porting\packages\Mods\Commanders\ | Measure-Object
# git status 应显示一堆 renamed
git -C e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace status --short | Select-String "renamed" | Measure-Object
```

预期：旧 7vs1 目录为空，新 Commanders 目录有 33 个 .SC2Mod，git status 有 33 行 renamed。

- [ ] **Step 5: 删除空的 7vs1 目录 + 临时脚本**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-rmdir.ps1" "e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\src\projects\cmre-porting\packages\Mods\7vs1"
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-rm.ps1" "$env:TEMP\migrate-mods.ps1"
```

- [ ] **Step 6: 检查 ALENGER_INVESTIGATION_REPORT.md 是否需迁移**

```powershell
# 这个报告之前在 7vs1 目录下，迁移时可能被遗留。如果还在，移到 Commanders 目录
Test-Path "e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\src\projects\cmre-porting\packages\Mods\7vs1\ALENGER_INVESTIGATION_REPORT.md"
```

如果存在，用 `git mv` 迁移到 `Commanders/` 目录。

---

## 任务 2：更新 alenger-mods.json 配置（key/value 改英文名）

**Files:**
- 修改: `src/config/alenger-mods.json`

**改动点：**
1. `commanderToAlenger` 的 key 从 `AlengerN` 改为英文名（如 `Empire`）
2. `commanderToAlenger` 的 value 数组中 mod 名同步改：
   - `Alenger1` → `SteelWallAlenger`
   - `Alenger1Adapter` → `SteelWallAlengerAdapter`
   - `Alenger6Common` → `SharedAlengerCommon`
   - `AlengerCommon` → `EmpireAlengerCommon`
3. `commanderProfiles` 的 key 同步改英文名
4. `commanderProfiles` 内部的 `adapterModName` 字段：`Alenger1Adapter` → `SteelWallAlengerAdapter`（这是 mod 目录名，需同步）
5. `adapterLibPrefix`（A1ADAPTER 等）和 `adapterFiles`（LibA1ADAPTER.galaxy 等）**保持不变**（galaxy 库前缀）
6. `workerCount` 已全部为 12（前置任务完成）

- [ ] **Step 1: 用 Edit 工具替换 commanderToAlenger 块**

将 `commanderToAlenger` 整块替换为：

```json
"commanderToAlenger": {
    "SteelWall": ["SharedAlengerCommon", "SteelWallAlenger", "SteelWallAlengerAdapter"],
    "Behemoth": ["SharedAlengerCommon", "BehemothAlenger", "BehemothAlengerAdapter"],
    "Empire": ["EmpireAlengerCommon", "EmpireAlenger", "EmpireAlengerAdapter"],
    "TalDarim": ["SharedAlengerCommon", "TalDarimAlenger", "TalDarimAlengerAdapter"],
    "Abathur": ["SharedAlengerCommon", "AbathurAlenger", "AbathurAlengerAdapter"],
    "Khalai": ["SharedAlengerCommon", "KhalaiAlenger", "KhalaiAlengerAdapter"],
    "Zagara": ["SharedAlengerCommon", "ZagaraAlenger", "ZagaraAlengerAdapter"],
    "Pirate": ["SharedAlengerCommon", "PirateAlenger", "PirateAlengerAdapter"],
    "Amon": ["SharedAlengerCommon", "AmonAlenger", "AmonAlengerAdapter"],
    "Community": ["SharedAlengerCommon", "CommunityAlenger", "CommunityAlengerAdapter"],
    "Ranger": ["SharedAlengerCommon", "RangerAlenger", "RangerAlengerAdapter"],
    "Purifier": ["SharedAlengerCommon", "PurifierAlenger", "PurifierAlengerAdapter"]
},
```

- [ ] **Step 2: 替换 commanderProfiles 中的 key 和 adapterModName**

每个 profile 的 key 从 `AlengerN` 改为英文名，`adapterModName` 从 `AlengerNAdapter` 改为 `<Eng>AlengerAdapter`。其他字段（adapterLibPrefix、adapterFiles、race、startingStructure、startingWorker、workerCount、vanillaRemovals）保持不变。

以 Empire（Alenger3）为例，从：
```json
"Alenger3": {
    "adapterModName": "Alenger3Adapter",
    ...
}
```
改为：
```json
"Empire": {
    "adapterModName": "EmpireAlengerAdapter",
    ...
}
```

对所有 12 个 profile 重复此操作。

- [ ] **Step 3: JSON 语法验证**

```powershell
python -c "import json; d=json.load(open(r'e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\src\config\alenger-mods.json',encoding='utf-8')); print('JSON valid'); print('keys:', list(d['commanderToAlenger'].keys())); print('Empire mods:', d['commanderToAlenger']['Empire']); print('Empire profile:', d['commanderProfiles']['Empire']['adapterModName'], d['commanderProfiles']['Empire']['workerCount'])"
```

预期：JSON valid，keys 为 12 个英文名，Empire mods 为 `['EmpireAlengerCommon', 'EmpireAlenger', 'EmpireAlengerAdapter']`，adapterModName 为 `EmpireAlengerAdapter`，workerCount 为 12。

- [ ] **Step 4: 检查其他文件是否引用 AlengerN 字符串**

```powershell
# 在 sc2-porting-workspace 内搜索 Alenger1/Alenger2/.../Alenger13 作为配置 key 的引用
# 排除 mod 内部 galaxy 代码（A1ADAPTER 等保持不变）和 GameStrings.txt（中文名映射）
cd e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace
git grep -n "Alenger[0-9]" -- "src/config/*.json" "tools/launchers/*.ps1" "tools/cmre-webui/*.py" "tools/cmre-webui/webui/*.js" "tools/cmre-webui/webui/*.html"
```

预期：应该只剩下 `Alenger` 作为通用词的引用（如 `Alenger` 后缀、`Alenger` 注释），不应有 `Alenger3` 作为 ID 的引用。如有遗漏，同步修改。

---

## 任务 3：改造 launch-cmre-alenger.ps1（路径 + 正则 + 模式参数 + PID 隔离）

**Files:**
- 修改: `tools/launchers/launch-cmre-alenger.ps1`

**改动点：**
1. param 块新增 `-PlayerMode` 和 `-DebugMode` 开关
2. 正则匹配从 `^(Terran|Zerg|Protoss)?(Alenger\d+)$` 改为枚举英文名
3. mod 路径从 `Mods/7vs1/$_.SC2Mod` 改为 `Mods/Commanders/$_.SC2Mod`
4. DebugMode 内部自动设 `$ApiMinimal = $true`，并要求 `-ListenPort > 0`
5. PlayerMode 和 DebugMode 互斥校验
6. 启动前清理逻辑按模式区分（PlayerMode 不清理，DebugMode 按 PID 文件清理，都不传走原逻辑）
7. DebugMode 启动 SC2 后写 PID 文件 + 最小化窗口
8. DebugMode 退出时 try/finally 关闭 SC2（按 PID）

- [ ] **Step 1: 修改 param 块，新增 -PlayerMode 和 -DebugMode**

第 2 行 param 块末尾追加两个开关（在 `-RebornSpeed = 5` 后）：

```powershell
[switch]$PlayerMode, [switch]$DebugMode
```

- [ ] **Step 2: 在 param 块后加模式校验**

在 `$ErrorActionPreference = "Stop"` 之后加：

```powershell
# 模式校验
if ($PlayerMode -and $DebugMode) { throw "-PlayerMode 和 -DebugMode 互斥，不能同时使用" }
if ($DebugMode) {
    if ($ListenPort -le 0) { throw "-DebugMode 必须配合 -ListenPort <port> 使用" }
    $ApiMinimal = $true  # DebugMode 内部自动启用 ApiMinimal
    Write-Host "DebugMode: 自动启用 ApiMinimal，SC2 窗口将最小化，launcher 退出时自动关闭 SC2"
}
```

- [ ] **Step 3: 修改正则匹配，从 AlengerN 改为英文名**

第 30 行附近，把：
```powershell
if ($Commander -match '^(Terran|Zerg|Protoss)?(Alenger\d+)$') {
    $isAlengerCommander = $true
    $alengerId = $Matches[2]
```
改为：
```powershell
$alengerNames = 'SteelWall|Behemoth|Empire|TalDarim|Abathur|Khalai|Zagara|Pirate|Amon|Community|Ranger|Purifier'
if ($Commander -match "^(Terran|Zerg|Protoss)?($alengerNames)$") {
    $isAlengerCommander = $true
    $alengerId = $Matches[2]
```

- [ ] **Step 4: 修改 mod 路径**

第 84 行附近和第 93 行附近，把所有 `Mods/7vs1/$_.SC2Mod` 改为 `Mods/Commanders/$_.SC2Mod`。同样把 `$AlengerPackagesRoot` 路径中如果有 `7vs1` 引用也要改（检查 `Join-Path $AlengerPackagesRoot "Mods\7vs1\..."` 改为 `Mods\Commanders\...`）。

搜索确认：
```powershell
git -C e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace grep -n "7vs1" -- tools/launchers/launch-cmre-alenger.ps1
```

所有命中行都改为 `Commanders`。

- [ ] **Step 5: 改造启动前清理逻辑（第 948-955 行）**

把原来的：
```powershell
$lock = Acquire-TestLock -TestType "cmre_alenger" -MapName $MapName -Commander $Commander
try {
    Stop-RunningSc2
    Get-Process -Name "SC2","StarCraft II" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep 2
    Clear-GameLogs
```

改为：
```powershell
$lock = Acquire-TestLock -TestType "cmre_alenger" -MapName $MapName -Commander $Commander
$debugPidFile = Join-Path $env:TEMP "cmre-debug-sc2.pid"
try {
    if ($PlayerMode) {
        # PlayerMode：不清理任何 SC2 进程，避免杀玩家游戏。已有 SC2 在跑则报错。
        $existing = Get-Process -Name "SC2_x64","SC2","StarCraft II" -ErrorAction SilentlyContinue
        if ($existing) {
            throw "检测到 SC2 已在运行（PID: $($existing.Id -join ',')）。PlayerMode 不会自动关闭已有游戏，请先手动关闭 SC2 再启动。"
        }
    } elseif ($DebugMode) {
        # DebugMode：只清理自己之前启动的 SC2（按 PID 文件，禁止按进程名 kill）
        if (Test-Path $debugPidFile) {
            $oldPid = Get-Content $debugPidFile -ErrorAction SilentlyContinue
            if ($oldPid) {
                Write-Host "DebugMode: 清理上次调试启动的 SC2 (PID=$oldPid)"
                Stop-Process -Id $oldPid -Force -ErrorAction SilentlyContinue
            }
            Remove-Item $debugPidFile -Force -ErrorAction SilentlyContinue
        }
        Start-Sleep 2
        Clear-GameLogs
    } else {
        # 命令行手动启动：走原有全量清理逻辑
        Stop-RunningSc2
        Get-Process -Name "SC2","StarCraft II" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep 2
        Clear-GameLogs
    }
```

- [ ] **Step 6: DebugMode 启动 SC2 后写 PID 文件 + 最小化窗口**

在 API 模式启动 SC2 后（第 1194 行 `Write-Host "SC2 API mode: API listening..."` 附近），加：

```powershell
# DebugMode 记录 PID 并最小化窗口
if ($DebugMode) {
    Set-Content -Path $debugPidFile -Value $proc.Id -Encoding UTF8
    Write-Host "DebugMode: SC2 PID $($proc.Id) 写入 $debugPidFile"
    # 最小化 SC2 窗口（Win32 API ShowWindowAsync, SW_MINIMIZE=6）
    try {
        $signature = '[DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);'
        $win32Type = Add-Type -MemberDefinition $signature -Name "Win32ShowWindowAsync" -Namespace Win32Functions -PassThru
        $minDeadline = (Get-Date).AddSeconds(30)
        while ((Get-Date) -lt $minDeadline) {
            $sc2Proc = Get-Process -Id $proc.Id -ErrorAction SilentlyContinue
            if ($sc2Proc -and $sc2Proc.MainWindowHandle -ne [IntPtr]::Zero) {
                $win32Type::ShowWindowAsync($sc2Proc.MainWindowHandle, 6) | Out-Null
                Write-Host "DebugMode: SC2 窗口已最小化"
                break
            }
            Start-Sleep -Milliseconds 500
        }
    } catch {
        Write-Host "DebugMode: 最小化窗口失败（非致命）: $_"
    }
}
```

注意：`$proc` 变量在 API 模式端口轮询循环中赋值，确认它在循环外仍可用。如果作用域有问题，重新 `Get-Process -Name "SC2_x64"` 取句柄。

- [ ] **Step 7: DebugMode 退出时 try/finally 关闭 SC2**

找到 launcher 的主 try 块结束位置（通常是文件末尾的 `finally { Release-TestLock $lock }`），在 finally 块内加：

```powershell
} finally {
    if ($DebugMode -and (Test-Path $debugPidFile)) {
        $debugPid = Get-Content $debugPidFile -ErrorAction SilentlyContinue
        if ($debugPid) {
            Write-Host "DebugMode: 退出时关闭 SC2 (PID=$debugPid)"
            Stop-Process -Id $debugPid -Force -ErrorAction SilentlyContinue
        }
        Remove-Item $debugPidFile -Force -ErrorAction SilentlyContinue
    }
    if ($null -ne $lock) { Release-TestLock $lock }
}
```

- [ ] **Step 8: PlayerMode 启动 SC2 后不主动关闭，但其他逻辑保持**

PlayerMode 走非 API 模式分支（`-ListenPort` 不传），原本第 1219-1224 行的 `Start-Process $switcher` + `Wait-GameReady` 逻辑保持不变。PlayerMode 不需要 PID 文件，不需要窗口最小化。

确认：PlayerMode 不会触发 API 模式分支（因为 `-ListenPort` 为 0）。

- [ ] **Step 9: DryRun 验证 Empire 配置加载**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\tools\launchers\launch-cmre-alenger.ps1" -MapName "亡者之夜" -Commander "Empire" -DryRun
```

预期输出包含：`Loaded commander profile for Empire: startingStructure=3diguoqianshaojidi, startingWorker=3diguolaogong`，并列出依赖（EmpireAlengerCommon/EmpireAlenger/EmpireAlengerAdapter）。

- [ ] **Step 10: DryRun 验证 -PlayerMode 和 -DebugMode 校验**

```powershell
# 互斥校验
powershell -NoProfile -ExecutionPolicy Bypass -File "...\launch-cmre-alenger.ps1" -MapName "亡者之夜" -Commander "Empire" -PlayerMode -DebugMode -DryRun
# 预期：报错 "-PlayerMode 和 -DebugMode 互斥"

# DebugMode 无端口
powershell -NoProfile -ExecutionPolicy Bypass -File "...\launch-cmre-alenger.ps1" -MapName "亡者之夜" -Commander "Empire" -DebugMode -DryRun
# 预期：报错 "-DebugMode 必须配合 -ListenPort"

# DebugMode + 端口（DryRun）
powershell -NoProfile -ExecutionPolicy Bypass -File "...\launch-cmre-alenger.ps1" -MapName "亡者之夜" -Commander "Empire" -DebugMode -ListenPort 5000 -DryRun
# 预期：输出 "DebugMode: 自动启用 ApiMinimal..." 并列依赖
```

---

## 任务 4：改造 server.py（CREATE_NO_WINDOW + 模式参数转发）

**Files:**
- 修改: `tools/cmre-webui/server.py`

**改动点：**
1. `subprocess.Popen` 加 `creationflags=subprocess.CREATE_NO_WINDOW`
2. WebUI 默认启动传 `-PlayerMode`
3. 勾选"SC2API 校准模式"时传 `-DebugMode -ListenPort <port>`（不再直接传 -ApiMinimal）

- [ ] **Step 1: 在 _handle_launch 中加 CREATE_NO_WINDOW 和模式参数**

找到 `subprocess.Popen(args, ...)` 调用（约第 752 行），改为：

```python
# 玩家模式默认，API 校准模式改用 DebugMode
is_api_mode = bool(api_minimal) or listen_port > 0
mode_args = []
if is_api_mode:
    mode_args = ["-DebugMode"]  # DebugMode 内部会自动设 ApiMinimal
else:
    mode_args = ["-PlayerMode"]

# 在原 args 构造中，移除独立的 -ApiMinimal（由 DebugMode 内部设）
# 保留 -ListenPort（DebugMode 要求必填）
args = [
    "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
    "-File", str(LAUNCH_SCRIPT),
    "-MapName", map_name,
    "-Commander", commander,
    "-LegacyRootOverride", LEGACY_ROOT,
    "-Mode", str(mode),
    "-DifficultyBase", str(difficulty_base),
    "-DifficultyPlus", str(difficulty_plus),
] + mode_args

# ... 原有 -Enemy/-Mutators 等追加逻辑 ...
if listen_port > 0:
    args.extend(["-ListenPort", str(listen_port)])
# 移除：if api_minimal: args.append("-ApiMinimal")  # 已由 -DebugMode 接管

proc = subprocess.Popen(
    args,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    encoding="utf-8",
    errors="replace",
    creationflags=subprocess.CREATE_NO_WINDOW,  # 隐藏 PS 控制台窗口
)
```

- [ ] **Step 2: 验证 server.py 语法**

```powershell
python -c "import py_compile; py_compile.compile(r'e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\tools\cmre-webui\server.py', doraise=True); print('OK')"
```

预期：OK。

---

## 任务 5：改造 AI 调试脚本 run-cmre-sc2api.ps1

**Files:**
- 修改: `tools/sc2api-baseline/scripts/run-cmre-sc2api.ps1`（如果存在）
- 修改: `sc2api-calibration/scripts/run-cmre-sc2api.ps1`（如果存在）

**改动点：**
- 把对 `launch-cmre-alenger.ps1` 的调用改为传 `-DebugMode -ListenPort <port>`，不再传 -ApiMinimal
- 把 `-Commander Alenger3` 改为 `-Commander Empire`（或其他英文名）

- [ ] **Step 1: 搜索所有调用 launch-cmre-alenger.ps1 的脚本**

```powershell
cd e:\Code\MyMod\SC2VibeTools
git grep -ln "launch-cmre-alenger" -- "*.ps1"
```

- [ ] **Step 2: 逐个修改调用点**

每个调用点：
- `-Commander AlengerN` → `-Commander <英文名>`
- 移除 `-ApiMinimal`（由 -DebugMode 接管）
- 添加 `-DebugMode`（如果原调用是 API 模式且有 -ListenPort）

- [ ] **Step 3: 验证脚本语法**

对每个修改的 .ps1 文件做语法检查：

```powershell
powershell -NoProfile -Command "& { [scriptblock]::Create((Get-Content -Raw '<file>')) | Out-Null; Write-Host 'OK' }"
```

---

## 任务 6：进图测试 - 玩家模式（PlayerMode）

**目标：** 验证 WebUI/launcher 玩家模式能正常启动游戏，开局 12 个农民，无 ScriptError。

- [ ] **Step 1: 确认 GameLogs 基线**

```powershell
ls "C:\Users\22448\Documents\StarCraft II\GameLogs" | Measure-Object
```

记录基线文件数。

- [ ] **Step 2: 用 launcher 直接启动 PlayerMode（绕过 WebUI 先测 launcher）**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\tools\launchers\launch-cmre-alenger.ps1" -MapName "亡者之夜" -Commander "Empire" -PlayerMode
```

预期：
- PS 控制台不弹出（被 CREATE_NO_WINDOW 隐藏）—— 注意：直接命令行调用不会触发 CREATE_NO_WINDOW，只有 WebUI Popen 才会。命令行测试时 PS 窗口会显示，这是正常的。
- SC2 游戏窗口正常显示
- launcher 退出码 0
- 开局 12 个帝国劳工

- [ ] **Step 3: 复核 GameLogs**

```powershell
ls "C:\Users\22448\Documents\StarCraft II\GameLogs" | Sort-Object LastWriteTime -Descending | Select-Object -First 5
```

检查是否有新增 `ScriptError.*.txt`。如有，先读取内容并修复。

- [ ] **Step 4: 关闭 SC2，清理**

手动关闭 SC2（PlayerMode 不自动关闭）。确认 GameLogs 无致命错误后继续。

- [ ] **Step 5: WebUI 玩家模式测试（可选，如果 WebUI 已运行）**

启动 WebUI，在界面选 Empire + 亡者之夜，点"启动游戏"（不勾选 SC2API 校准模式）。预期：
- PS 控制台不弹出
- SC2 游戏窗口正常显示
- 开局 12 个农民

---

## 任务 7：进图测试 - 调试模式（DebugMode）

**目标：** 验证调试模式 SC2 窗口最小化、PID 文件正确、API 端口可连、退出时自动关闭。

- [ ] **Step 1: 启动 DebugMode**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\tools\launchers\launch-cmre-alenger.ps1" -MapName "亡者之夜" -Commander "Empire" -DebugMode -ListenPort 5000
```

预期：
- SC2 启动后窗口自动最小化
- 输出 "DebugMode: SC2 PID <pid> 写入 ..."
- 输出 "DebugMode: SC2 窗口已最小化"
- API 端口 5000 可连

- [ ] **Step 2: 验证 PID 文件**

```powershell
Get-Content "$env:TEMP\cmre-debug-sc2.pid"
# 应为 SC2_x64 的 PID
Get-Process -Id (Get-Content "$env:TEMP\cmre-debug-sc2.pid") | Select-Object Name, Id, MainWindowTitle
```

- [ ] **Step 3: 验证 API 端口可连**

```powershell
$tcp = New-Object System.Net.Sockets.TcpClient
$iar = $tcp.BeginConnect("127.0.0.1", 5000, $null, $null)
$ok = $iar.AsyncWaitHandle.WaitOne(2000)
if ($ok -and $tcp.Connected) { Write-Host "API port 5000 OK" } else { Write-Host "API port 5000 FAIL" }
$tcp.Close()
```

- [ ] **Step 4: 验证窗口已最小化**

```powershell
# SC2 窗口应在任务栏，不抢占焦点
Get-Process -Name "SC2_x64" | Select-Object Name, Id, MainWindowTitle, Responding
```

- [ ] **Step 5: Ctrl+C 终止 launcher，验证自动关闭 SC2**

在 launcher 的终端按 Ctrl+C，或用 StopCommand 终止。预期：
- launcher finally 块输出 "DebugMode: 退出时关闭 SC2 (PID=...)"
- SC2_x64 进程被关闭
- PID 文件被删除

```powershell
# 验证 SC2 已关闭
Get-Process -Name "SC2_x64" -ErrorAction SilentlyContinue
# 应为空

# 验证 PID 文件已删
Test-Path "$env:TEMP\cmre-debug-sc2.pid"
# 应为 False
```

- [ ] **Step 6: 验证 DebugMode 不杀玩家游戏（关键隔离测试）**

模拟玩家游戏在跑，启动 DebugMode：
1. 手动启动一个 SC2（用 PlayerMode 或直接 SC2Switcher），让它在主菜单
2. 记录这个玩家 SC2 的 PID
3. 启动 DebugMode（不同端口）：
   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File "...\launch-cmre-alenger.ps1" -MapName "亡者之夜" -Commander "Empire" -DebugMode -ListenPort 5001
   ```
4. 验证玩家 SC2（步骤 1 的 PID）**仍在运行**，未被杀
5. DebugMode 退出后，验证玩家 SC2 仍存活

```powershell
# 步骤 1 的 PID 应该还在
Get-Process -Id <玩家SC2_PID>
# 应返回进程信息，不是报错
```

---

## 任务 8：git commit + push

- [ ] **Step 1: git status 复核**

```powershell
cd e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace
git status
git diff --stat
```

确认改动范围：
- alenger-mods.json（配置改动）
- launch-cmre-alenger.ps1（launcher 改造）
- server.py（WebUI 改造）
- 33 个 mod 目录 renamed
- docs/specs/2026-07-26-*.md（设计文档）
- docs/superpowers/plans/2026-07-26-*.md（本计划）

- [ ] **Step 2: git add 明确文件**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-add.ps1" "src/config/alenger-mods.json" "tools/launchers/launch-cmre-alenger.ps1" "tools/cmre-webui/server.py" "docs/specs/2026-07-26-mod-rename-and-launcher-refactor-design.md" "docs/superpowers/plans/2026-07-26-mod-rename-and-launcher-refactor-plan.md"
# mod 目录 renamed 用 git add -A 限制在 Commanders 目录（或 git add 具体路径）
# 由于 git mv 已经 stage 了重命名，这里只需 add 配置和脚本文件
```

注意：git mv 已经把 mod 重命名放入暂存区，无需再 add。但新增的 Commanders 目录和删除的 7vs1 目录需要确认已 stage。

- [ ] **Step 3: git commit**

```powershell
$msg = "重构：起义指挥官 mod 重命名+迁移到 Commanders 目录，launcher 区分玩家/AI 调试模式`n`n- mod 目录从 Mods/7vs1/ 迁移到 Mods/Commanders/，12 个指挥官 mod+Adapter 重命名为英文名+Alenger 后缀（如 EmpireAlenger.SC2Mod）`n- alenger-mods.json 的 key/value 同步改为英文名（如 -Commander Empire）`n- launcher 新增 -PlayerMode/-DebugMode 互斥开关，DebugMode 自动启用 ApiMinimal+最小化窗口+PID 文件隔离`n- DebugMode 启动前只清理自己启动的 SC2（按 PID 文件），禁止按进程名 kill，避免误杀玩家游戏`n- server.py 加 CREATE_NO_WINDOW 隐藏 PS 控制台，默认传 -PlayerMode，API 校准改传 -DebugMode`n- workerCount 统一为 12（修复人族/星族开局农民数与原版 RaceData.xml 不一致）"
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-commit.ps1" $msg
```

- [ ] **Step 4: git push（如果有 remote）**

```powershell
cd e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace
git remote -v
# 如果有 remote，push；如果没有，跳过
```

---

## 自检清单

- [ ] 33 个 mod 目录已迁移到 `Mods/Commanders/`，旧 `7vs1/` 目录已删除
- [ ] alenger-mods.json 的 key 全部为英文名，Empire 的 mods 列表为 `[EmpireAlengerCommon, EmpireAlenger, EmpireAlengerAdapter]`
- [ ] launcher 正则匹配英文名，mod 路径用 `Mods/Commanders/`
- [ ] `-PlayerMode` 不清理 SC2 进程，已有 SC2 在跑则报错
- [ ] `-DebugMode` 按 PID 文件清理，禁止按进程名 kill
- [ ] DebugMode 启动后写 PID 文件 + 最小化窗口
- [ ] DebugMode 退出时 finally 块按 PID 关闭 SC2 + 删 PID 文件
- [ ] server.py 加 CREATE_NO_WINDOW，默认 -PlayerMode，API 模式传 -DebugMode
- [ ] DryRun 验证 Empire 配置加载（workerCount=12）
- [ ] 玩家模式进图测试：开局 12 个农民，无 ScriptError
- [ ] 调试模式测试：窗口最小化、PID 文件、API 端口、自动关闭
- [ ] 隔离测试：DebugMode 不杀玩家 SC2
- [ ] git commit + push 完成
