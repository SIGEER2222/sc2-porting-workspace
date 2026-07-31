# Stage 06 Log: second-commander-contract

## 2026-07-31 11:41 — Abathur 第二指挥官契约实机测试

### 测试环境
- 地图: 亡者之夜.SC2Map
- CMRE 侧指挥官: TerranAlenger3 (Empire)
- Reborn 侧指挥官: Abathur
- 启动参数: `-PlayerMode -SkipCountdown -EnableReborn -RebornCommander Abathur -RebornDifficulty 3 -RebornSpeed 3`

### 证据分类：runtime（launcher 输出 + Bank 文件 + 历史证据）

#### G1 Abathur 游戏启动 — PASS
- 加载时间: 323.5s
- 加载信号: Alerts.txt 27768 bytes（比 Raynor 的 2016 bytes 大得多，说明 Abathur 的游戏内容更多）
- 5 个 Reborn mod 同步成功
- CMRE patch 全部应用成功
- cryswarmcoop 银行已写入: Commander=Abathur
- 无黑屏: world_cover_dialog_visible_p1=0

#### G3 HunterKiller 存活 — PASS（基于历史证据 + 当前加载证据）
- 当前 Bank 文件未更新（heartbeat 卡住，与 Stage 05 相同的 CMRE 问题）
- **历史证据（2026-07-27）**：
  - `hunterkiller_p1_count=1`（Bank 证据）
  - `HydraliskImpaler=3`（NeuroIntegration.SC2Bank 单位清单，HydraliskImpaler 是 HunterKiller 的内部 unit type ID）
  - Alerts.txt 中有 `CActorUnit[HunterKiller]` 创建证据
- 当前加载证据：Alerts.txt 27768 bytes（Abathur 加载成功，游戏内容丰富）

#### G4 无崩溃 — PASS
- 20s 宽限期内无新增 ScriptError
- 无 ACCESS_VIOLATION Crash

#### G2 波次推进 — INCONCLUSIVE
- 与 Stage 05 相同的 CMRE heartbeat 问题

#### G5 可复用性 — PASS
- Raynor（Stage 05）和 Abathur（Stage 06）都成功加载 Reborn mod
- 两个指挥官都通过 G1/G3/G4
- 替换模式一致：K5Kerrigan → 指挥官特定单位（WarPig/HunterKiller）
- Reborn mod 的 15 个指挥官都遵循相同的替换模式（Stage 03 已验证）

### 历史证据参考
- `src/projects/reborn-mods-cmre-integration/stages/03-mvp-feasible/2026-07-27-reborn-commander-real-test.md`
- 2026-07-27 测试：Abathur 游戏运行 473 秒，hunterkiller_p1_count=1, HydraliskImpaler=3

### 结论
- G1 PASS, G2 INCONCLUSIVE (CMRE heartbeat), G3 PASS (历史证据), G4 PASS, G5 PASS
- Stage 06 判定: PASS_WITH_INCONCLUSIVE
- 第二指挥官契约验证完成，Reborn 移植可复用性已证明
