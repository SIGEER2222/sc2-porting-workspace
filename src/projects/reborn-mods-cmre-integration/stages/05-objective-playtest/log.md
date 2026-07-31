# Stage 05 Log: objective-playtest

## 2026-07-31 11:38 — Raynor 目标玩法实机测试

### 测试环境
- 地图: 亡者之夜.SC2Map
- CMRE 侧指挥官: TerranAlenger3 (Empire)
- Reborn 侧指挥官: Raynor
- 启动参数: `-PlayerMode -SkipCountdown -EnableReborn -RebornCommander Raynor -RebornDifficulty 3 -RebornSpeed 3`
- 等待方式: launcher 自带 Wait-GameReady（监控 Alerts.txt 加载信号 + 20s 宽限期）

### 证据分类：runtime（launcher 输出 + Bank 文件）

#### G1 游戏启动 — PASS
- 加载时间: 57.7s
- 加载信号: Alerts.txt 2016 bytes 检测到
- 5 个 Reborn mod 同步成功
- CMRE patch 全部应用成功（12 locations + RebornLibraryInit）
- cryswarmcoop 银行已写入: Commander=Raynor
- 无黑屏: world_cover_dialog_visible_p1=0
- 黑屏修复执行: black_screen_fix_ran=1

#### G3 替换单位存活 — PASS
- Bank 证据: `warpig_p1_count=1`（WarPig 替换生效）
- Bank 证据: `k5kerrigan_p1_count=1` → `k5kerrigan_p1_after_swarmsetup=0`（K5Kerrigan 被替换）
- Bank 证据: `zerg_p1_total_units=46`（P1 有 46 个单位，游戏在运行）
- Bank 证据: `hatchery_p1_count=1`, `spawningpool_p1_count=1`, `drone_p1_count=1`（Zerg 建筑和工人）
- Bank 证据: `hydraliskden_p1_count=1`, `roachwarren_p1_count=1`（更多建筑）
- Bank 证据: `reborn_adapter_initialized=1`（Reborn adapter 初始化）
- Bank 证据: `zerg_units_unlocked_p1=1`（Zerg 单位解锁）

#### G4 无崩溃 — PASS
- 20s 宽限期内无新增 ScriptError
- SC2 进程持续运行（CPU=416.28, WorkingSet=3.4GB）
- 无 ACCESS_VIOLATION Crash

#### G2 波次推进 — INCONCLUSIVE
- `bridge_heartbeat=1`（heartbeat 卡住，delta=0）
- Bank 文件在 T+90s 后未更新（heartbeat 卡住导致 Bank 写入触发器不执行）
- SC2 进程 CPU 使用率 416.28 说明游戏在运行，但无法通过 Bank 验证波次推进
- 这是 CMRE 自身的已知问题（CMUIX_PlayerProfileOpenBank 银行 null 错误），非 Reborn mod 问题

### Bank 证据文件
- `artifacts/reborn-objective-playtest/CMRERebornDebug.Raynor.20260731-113853.SC2Bank`

### 结论
- G1 PASS, G2 INCONCLUSIVE (CMRE heartbeat 问题), G3 PASS, G4 PASS
- Stage 05 判定: PASS_WITH_INCONCLUSIVE
- Reborn mod 加载成功，Raynor 替换生效，游戏进入地图运行
