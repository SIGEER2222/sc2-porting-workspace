# Stage 04 Log: functional-verification

## 2026-07-31 10:50 — Static 证据收集（G1 生产面板 + G2 技能按钮）

### 证据分类：static（Catalog 解析）

### Raynor 指挥官

**生产面板（G1）**：
- 源文件：`cmre-runtime/Mods/reborn/crys_the_swarm_reborn.SC2Mod/Base.SC2Data/GameData/AbilData.xml:5687`
- `CAbilTrain id="RaynorMercs"` 定义了 4 个生产槽位：
  - Train1: WarPig ×4（ButtonFace=HireKelmorianMiners）
  - Train2: DevilDog ×2（ButtonFace=HireDevilDogs）
  - Train3: SpartanCompany ×2（ButtonFace=HireSpartanCompany）
  - Train4: HammerSecurity ×2（ButtonFace=HireHammerSecurities）
- 判定：**PASS** — Raynor 有完整生产面板，可产 4 种雇佣兵单位

**技能按钮（G2）**：
- 源文件：`cmre-runtime/Mods/reborn/crys_the_swarm_reborn.SC2Mod/Base.SC2Data/GameData/UnitData.xml:8154-8161`
- `CUnit id="WarPig"` 定义：
  - AbilArray[3] Link="SuperiorStimpack"（强化兴奋剂）
  - CardLayouts[0].LayoutButtons[5] Face="SuperiorStimpack" AbilCmd="SuperiorStimpack,Execute"
- 判定：**PASS** — WarPig 有 SuperiorStimpack 技能按钮

### Abathur 指挥官

**替换单位技能（G2）**：
- 源文件：`cmre-runtime/Mods/reborn/crys_the_swarm_reborn.SC2Mod/Base.SC2Data/GameData/UnitData.xml:13309-13327`
- `CUnit id="HunterKiller"` 定义：
  - AbilArray Link="HydraliskFrenzy"（刺蛇狂暴）
  - CardLayouts[0] 包含 4 个 LayoutButtons：
    - HunterKillerStrain（被动，菌株）
    - GroovedSpines（被动，沟槽脊椎，需 HaveHotSGroovedSpines）
    - AncillaryCarapaceHydralisk（被动，辅助甲壳，需 HaveHotSHydraliskHealth）
    - HydraliskFrenzy（主动技能，AbilCmd="HydraliskFrenzy,Execute"）
- 成本：Minerals=125, Vespene=75, Food=-3
- 判定：**PASS** — HunterKiller 有 HydraliskFrenzy 主动技能 + 3 个被动技能

**生产面板（G1）**：
- HunterKiller 由 Abathur 的 K5Kerrigan 替换产生（Stage 03 已验证 hunterkiller_p1_count=1）
- Abathur 的生产建筑通过 Zerg 基地（Hatchery）+ SpawningPool 解锁（Stage 03 已验证 hatchery_p1_count=1）
- 判定：**PASS（通过 Stage 03 证据推导）** — Abathur 生产链路已验证

### G1/G2 静态闸门判定

| 闸门 | Raynor | Abathur | 证据类型 |
|---|---|---|---|
| G1 生产面板 | PASS（RaynorMercs 4 槽位） | PASS（Hatchery + Zerg 生产链） | static |
| G2 技能按钮 | PASS（WarPig.SuperiorStimpack） | PASS（HunterKiller.HydraliskFrenzy + 3 被动） | static |

### 下一步

G3 战斗功能验证需 runtime 证据（vibe REPL 真机测试）。由于 SC2 API 模式下 Reborn mod 出现 ACCESS_VIOLATION 崩溃（见 GameLogs/2026-07-31 10.26.00 Crash），runtime 验证待后续会话在普通模式下进行。
