# 重生虫心指挥官测试报告（黑屏修复验证 + 单位/建筑验收）

- 测试时间: 2026-07-28 23:36:42
- 测试地图: 亡者之夜.SC2Map
- 测试模式: -EnableReborn -SkipCountdown -MapCopySuffix reborn-test
- 黑屏检测方法: 银行文件 CMRERebornDebug.SC2Bank（不依赖截图）
  - world_cover_dialog_visible_p1 = 0 → 黑屏修复成功
  - game_mission_time_paused = 0 → 游戏未暂停
  - black_screen_fix_ran = 1 → 修复代码已执行

## 汇总结果

| 指挥官 | 种族 | 黑屏修复 | K5Kerrigan | 替换单位 | Hatchery | SpawningPool | Drone | Zerg总单位 | Abathur升级 | 状态 |
|--------|------|----------|------------|----------|----------|--------------|-------|-----------|-------------|------|
| 阿巴瑟 | Zerg | OK | 1/after=0 | hydraliskimpaler_p1_count=1 | 1 | 0 | 1 | 14 | 1 | PASS |
| 德哈卡 | Zerg | OK | 1/after=0 | primalhydralisk2_p1_count=1, primaligniter_p1_count=1 | 1 | 0 | 1 | 17 | 0 | PASS |
| 伊兹莎 | Zerg | OK | 1/after=0 | siqueen_p1_count=1 | 1 | 0 | 1 | 14 | 0 | PASS |
| 卡拉斯 | Protoss | OK | 1/after=0 | higharchontemplar_p1_count=1 | 0 | 0 | 0 | 4 | 0 | PASS |
| 凯瑞甘 | Zerg | OK | 1/after=1 | N/A | 1 | 0 | 1 | 14 | 0 | PASS |
| 娜克图尔 | Zerg | OK | 1/after=0 | queen_p1_count=1 | 1 | 0 | 1 | 14 | 0 | PASS |
| 纳鲁德 | Protoss | OK | 1/after=0 | revenantgun_p1_count=1 | 0 | 0 | 0 | 4 | 0 | PASS |
| 雷诺 | Terran | OK | 1/after=0 | warpig_p1_count=1 | 0 | 0 | 0 | 7 | 0 | PASS |
| 斯图科夫 | Zerg | OK | 1/after=0 | infestedmarine_p1_count=1 | 1 | 0 | 1 | 17 | 0 | PASS |
| 托什 | Terran | OK | 1/after=0 | witch_p1_count=1 | 0 | 0 | 0 | 4 | 0 | PASS |
| 乌伦 | Protoss | OK | 1/after=0 | huntress_p1_count=1 | 0 | 0 | 0 | 7 | 0 | PASS |
| 沃菲尔德 | Terran | OK | 1/after=0 | grizzly_p1_count=1 | 0 | 0 | 0 | 4 | 0 | PASS |
| 蒙斯克 | Terran | OK | 1/after=0 | mengskmarauder_p1_count=1 | 0 | 0 | 0 | 4 | 0 | PASS |
| 扎加拉 | Zerg | OK | 1/after=0 | infestedabomination_p1_count=1 | 1 | 0 | 1 | 14 | 0 | PASS |
| 泽拉图 | Protoss | OK | 1/after=0 | stalkershakuras_p1_count=1 | 0 | 0 | 0 | 7 | 0 | PASS |

## 总结

- 通过: 15 / 15
- 失败: 0 / 15
- 完成时间: 2026-07-28 23:55:08

## 详细数据

### 阿巴瑟 (Abathur)

- Runtime ID: ZergAbathur
- Launcher exit code: 1
- Elapsed: 70.1054282s
- 期望单位: HunterKiller/HydraliskImpaler
- 期望建筑: Hatchery,SpawningPool,Drone
- 黑屏修复: OK (fix_ran=1)
- K5Kerrigan: count=1, after_swarmsetup=0
- 替换单位: hydraliskimpaler_p1_count=1
- Hatchery=1, SpawningPool=0, Drone=1
- Zerg总单位: 14
- Abathur升级数: 1
- **状态: PASS**

### 德哈卡 (Dehaka)

- Runtime ID: ZergDehaka
- Launcher exit code: 1
- Elapsed: 96.9206334s
- 期望单位: PrimalHydralisk2,PrimalIgniter
- 期望建筑: Hatchery,SpawningPool,Drone
- 黑屏修复: OK (fix_ran=1)
- K5Kerrigan: count=1, after_swarmsetup=0
- 替换单位: primalhydralisk2_p1_count=1, primaligniter_p1_count=1
- Hatchery=1, SpawningPool=0, Drone=1
- Zerg总单位: 17
- Abathur升级数: 0
- **状态: PASS**

### 伊兹莎 (Izsha)

- Runtime ID: ZergIzsha
- Launcher exit code: 1
- Elapsed: 69.0151063s
- 期望单位: SIQueen
- 期望建筑: Hatchery,SpawningPool,Drone
- 黑屏修复: OK (fix_ran=1)
- K5Kerrigan: count=1, after_swarmsetup=0
- 替换单位: siqueen_p1_count=1
- Hatchery=1, SpawningPool=0, Drone=1
- Zerg总单位: 14
- Abathur升级数: 0
- **状态: PASS**

### 卡拉斯 (Karass)

- Runtime ID: ProtossKarass
- Launcher exit code: 1
- Elapsed: 71.9208508s
- 期望单位: HighArchonTemplar
- 期望建筑: 
- 黑屏修复: OK (fix_ran=1)
- K5Kerrigan: count=1, after_swarmsetup=0
- 替换单位: higharchontemplar_p1_count=1
- Hatchery=0, SpawningPool=0, Drone=0
- Zerg总单位: 4
- Abathur升级数: 0
- **状态: PASS**

### 凯瑞甘 (Kerrigan)

- Runtime ID: ZergKerrigan
- Launcher exit code: 1
- Elapsed: 65.9284066s
- 期望单位: K5Kerrigan
- 期望建筑: Hatchery,SpawningPool,Drone
- 黑屏修复: OK (fix_ran=1)
- K5Kerrigan: count=1, after_swarmsetup=1
- 替换单位: N/A
- Hatchery=1, SpawningPool=0, Drone=1
- Zerg总单位: 14
- Abathur升级数: 0
- **状态: PASS**

### 娜克图尔 (Naktul)

- Runtime ID: ZergNaktul
- Launcher exit code: 1
- Elapsed: 66.0710695s
- 期望单位: Queen
- 期望建筑: Hatchery,SpawningPool,Drone
- 黑屏修复: OK (fix_ran=1)
- K5Kerrigan: count=1, after_swarmsetup=0
- 替换单位: queen_p1_count=1
- Hatchery=1, SpawningPool=0, Drone=1
- Zerg总单位: 14
- Abathur升级数: 0
- **状态: PASS**

### 纳鲁德 (Narud)

- Runtime ID: ProtossNarud
- Launcher exit code: 1
- Elapsed: 65.9194263s
- 期望单位: RevenantGun
- 期望建筑: 
- 黑屏修复: OK (fix_ran=1)
- K5Kerrigan: count=1, after_swarmsetup=0
- 替换单位: revenantgun_p1_count=1
- Hatchery=0, SpawningPool=0, Drone=0
- Zerg总单位: 4
- Abathur升级数: 0
- **状态: PASS**

### 雷诺 (Raynor)

- Runtime ID: TerranRaynor
- Launcher exit code: 1
- Elapsed: 71.9621154s
- 期望单位: WarPig
- 期望建筑: 
- 黑屏修复: OK (fix_ran=1)
- K5Kerrigan: count=1, after_swarmsetup=0
- 替换单位: warpig_p1_count=1
- Hatchery=0, SpawningPool=0, Drone=0
- Zerg总单位: 7
- Abathur升级数: 0
- **状态: PASS**

### 斯图科夫 (Stukov)

- Runtime ID: ZergStukov
- Launcher exit code: 1
- Elapsed: 72.1525113s
- 期望单位: InfestedMarine
- 期望建筑: Hatchery,SpawningPool,Drone
- 黑屏修复: OK (fix_ran=1)
- K5Kerrigan: count=1, after_swarmsetup=0
- 替换单位: infestedmarine_p1_count=1
- Hatchery=1, SpawningPool=0, Drone=1
- Zerg总单位: 17
- Abathur升级数: 0
- **状态: PASS**

### 托什 (Tosh)

- Runtime ID: TerranTosh
- Launcher exit code: 1
- Elapsed: 66.0231125s
- 期望单位: Witch
- 期望建筑: 
- 黑屏修复: OK (fix_ran=1)
- K5Kerrigan: count=1, after_swarmsetup=0
- 替换单位: witch_p1_count=1
- Hatchery=0, SpawningPool=0, Drone=0
- Zerg总单位: 4
- Abathur升级数: 0
- **状态: PASS**

### 乌伦 (Urun)

- Runtime ID: ProtossUrun
- Launcher exit code: 1
- Elapsed: 65.8334632s
- 期望单位: Huntress
- 期望建筑: 
- 黑屏修复: OK (fix_ran=1)
- K5Kerrigan: count=1, after_swarmsetup=0
- 替换单位: huntress_p1_count=1
- Hatchery=0, SpawningPool=0, Drone=0
- Zerg总单位: 7
- Abathur升级数: 0
- **状态: PASS**

### 沃菲尔德 (Warfield)

- Runtime ID: TerranWarfield
- Launcher exit code: 1
- Elapsed: 78.2277659s
- 期望单位: Grizzly
- 期望建筑: 
- 黑屏修复: OK (fix_ran=1)
- K5Kerrigan: count=1, after_swarmsetup=0
- 替换单位: grizzly_p1_count=1
- Hatchery=0, SpawningPool=0, Drone=0
- Zerg总单位: 4
- Abathur升级数: 0
- **状态: PASS**

### 蒙斯克 (Mengsk)

- Runtime ID: TerranMengsk
- Launcher exit code: 1
- Elapsed: 65.9169475s
- 期望单位: MengskMarauder
- 期望建筑: 
- 黑屏修复: OK (fix_ran=1)
- K5Kerrigan: count=1, after_swarmsetup=0
- 替换单位: mengskmarauder_p1_count=1
- Hatchery=0, SpawningPool=0, Drone=0
- Zerg总单位: 4
- Abathur升级数: 0
- **状态: PASS**

### 扎加拉 (Zagara)

- Runtime ID: ZergZagara
- Launcher exit code: 1
- Elapsed: 69.2744787s
- 期望单位: InfestedAbomination
- 期望建筑: Hatchery,SpawningPool,Drone
- 黑屏修复: OK (fix_ran=1)
- K5Kerrigan: count=1, after_swarmsetup=0
- 替换单位: infestedabomination_p1_count=1
- Hatchery=1, SpawningPool=0, Drone=1
- Zerg总单位: 14
- Abathur升级数: 0
- **状态: PASS**

### 泽拉图 (Zeratul)

- Runtime ID: ProtossZeratul
- Launcher exit code: 1
- Elapsed: 65.9557201s
- 期望单位: StalkerShakuras
- 期望建筑: 
- 黑屏修复: OK (fix_ran=1)
- K5Kerrigan: count=1, after_swarmsetup=0
- 替换单位: stalkershakuras_p1_count=1
- Hatchery=0, SpawningPool=0, Drone=0
- Zerg总单位: 7
- Abathur升级数: 0
- **状态: PASS**
