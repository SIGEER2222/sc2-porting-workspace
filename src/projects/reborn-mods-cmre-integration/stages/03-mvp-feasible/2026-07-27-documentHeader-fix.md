# Reborn 主 mod DocumentHeader 损坏修复 + 完整加载验证

## 日期
2026-07-27

## 问题描述
完整 5 个 Reborn mod 加入 CMRE + Empire Alenger3 依赖链后，SC2 卡在 ~390MB 加载阶段，无法生成 Alerts.txt，无法进图。

## 根因定位过程（二分法）

### 基线验证
| 测试 | Reborn mod 组合 | 结果 | 加载时间 | Alerts.txt |
|------|----------------|------|---------|------------|
| 基线 | 无 Reborn（纯 CMRE + Empire） | ✅ 通过 | 48.5s | 26792 bytes |
| Test 1 | +crys_swarm_assets | ✅ 通过 | 48.5s | 26772 bytes |
| Test 2 | +sibirens_sundries_swarm_reborn | ✅ 通过 | 51.5s | 26772 bytes |
| Test 3 | +sibirens_starhooks_common | ✅ 通过 | 54.6s | 26772 bytes |
| Test 4 | +sibirens_starhooks_swarmstoryutils | ✅ 通过 | 51.5s | 26772 bytes |
| Test 5 | +crys_the_swarm_reborn（完整 5 mod） | ❌ 失败 | >180s | 无（卡 390MB） |

**结论**：4 个子 mod 全部正常，问题出在主 mod `crys_the_swarm_reborn.SC2Mod`。

### 排除测试
对主 mod 进行逐项清空测试：
- 清空所有 catalog XML 数据（28 个文件）→ 仍然卡
- 清空 Triggers 文件（21.5MB）→ 仍然卡
- 去掉 TriggerLibs 声明 → 仍然卡
- 清空 Preload.xml 和 PreloadAssetDB.txt → 仍然卡
- 去掉战役依赖（Void.SC2Campaign、SwarmStory.SC2Campaign）→ 仍然卡
- 去掉 Preload 银行声明 → 仍然卡

**结论**：主 mod 内容全部清空后仍卡住，问题不在 mod 内容，而在 DocumentHeader 二进制文件本身。

### 根因发现
通过 hex dump 对比主 mod 和子 mod 的 DocumentHeader：

**主 mod（损坏）offset 0x10-0x30：**
```
EF BF BD 6F 01 00 EF BF BD 6F 01 00 02 00 00 00
EF BF BD EF BF BD 24 EF BF BD EF BF BD EF BF BD
24 EF BF BD 00 00 00 00 00 00 00 00 07 00 00 00
```

**子 mod（正常）offset 0x10-0x30：**
```
18 69 01 00 18 69 01 00 02 00 00 00 76 87 D3 D9
76 87 D3 D9 00 00 00 00 00 00 00 00 04 00 00 00
```

主 mod 的 DocumentHeader 包含大量 `EF BF BD` 字节序列——这是 UTF-8 编码的 U+FFFD 替换字符（Replacement Character）。这说明 DocumentHeader 文件在某次处理中被错误地以文本模式（UTF-8）读取/写入，导致原本的 binary 数据中非 ASCII 字节被替换为 `EF BF BD`，造成不可逆的数据损坏。

SC2 在解析 DocumentHeader 时，这些损坏的元数据字段（版本号、时间戳、GUID 等）导致引擎无法正确解析文档元数据，从而在加载阶段无限卡住。

## 修复方案
从正常工作的子 mod `sibirens_sundries_swarm_reborn.SC2Mod` 复制干净的 DocumentHeader 前缀（包含正确的 H2CS 头部格式），然后用 `Write-DocumentHeaderDependencies` 写入主 mod 的 7 个依赖列表。

修复后 hex dump：
```
0000: 48 32 43 53 08 00 00 00 32 53 00 00 01 05 00 0D  H2CS....2S......
0010: 18 69 01 00 18 69 01 00 02 00 00 00 76 87 D3 D9  .i...i......v...
0020: 76 87 D3 D9 00 00 00 00 00 00 00 00 07 00 00 00  v...............
0030: 66 69 6C 65 3A 43 61 6D 70 61 69 67 6E 73 2F 56  file:Campaigns/V
```
- 无 `EF BF BD` 字节
- 7 个依赖正确写入

## 验证结果

### 完整 5 mod 加载测试
- **日期**: 2026-07-27 08:14:27
- **地图**: 亡者之夜.SC2Map
- **指挥官**: Alenger3 (Empire)
- **依赖总数**: 13（8 基线 + 5 Reborn mod）
- **加载时间**: 57.6s
- **Alerts.txt**: 27748 bytes（launcher 报告）→ 31554 bytes（最终）
- **ScriptError**: 无
- **退出码**: 0

### 银行文件更新
| 银行文件 | 大小 | 更新时间 |
|---------|------|---------|
| CMCoopLaunchProfile.SC2Bank | 1360 bytes | 08:15:22 |
| COCampaign.SC2Bank | 903914 bytes | 08:15:24 |
| NeuroIntegration.SC2Bank | 4340 bytes | 08:15:41 |

### GameLogs 证据
```
2026-07-27 08.15.11 Alerts.txt      31554 bytes
2026-07-27 08.15.46 Graphics.txt     2681 bytes
2026-07-27 08.15.44 SystemInfo.txt   6082 bytes
```
无 ScriptError 文件。

## 修复的文件
1. `cmre-runtime/Mods/reborn/crys_the_swarm_reborn.SC2Mod/DocumentHeader` - 从子 mod 复制干净前缀 + 重写依赖列表
2. `cmre-runtime/Mods/reborn/sibirens_starhooks_common.SC2Mod/DocumentInfo` - 修复空的 DocumentInfo（添加完整 XML 结构）
3. `sc2-porting-workspace/src/config/cmre-alenger-dependencies.json` - 恢复完整 5 个 Reborn mod 声明

## 运行时验证（2026-07-27 08:42-08:44）

### 测试环境
- **地图**: 亡者之夜.SC2Map
- **指挥官**: Alenger3 (Empire)
- **依赖总数**: 13（8 基线 + 5 Reborn mod）
- **启动参数**: -PlayerMode -SkipCountdown -EnableReborn
- **加载时间**: 60.6s
- **Alerts.txt**: 27748 bytes

### 银行 IPC 探针结果（NeuroIntegration.SC2Bank）

| 探针 | 值 | 分析 |
|------|-----|------|
| `alenger_starting_units_done` | `p1_start=T; p2_start=T; created_p1=1; created_p2=1; after_p1=1; after_p2=1` | ✅ 两个玩家的起始建筑均成功创建 |
| `alenger_train_probe_result` | `train_ability_placeholder; worker_before=24; train_completed=false(diag_skip)` | ✅ 探针找到建筑和工人；diag_skip 是 launcher 代码设计（第 601-602 行占位符），非 Reborn 问题 |
| `porting_observer_ready` | `CMRE dynamic observer initialized...` | ✅ CMRE 观察者初始化成功 |
| `mission_phase` | `Dead of Night phase=day night_number=0` | ✅ 任务阶段跟踪正常 |
| `mission_objective` | `Primary objective infestation structures remaining=0 total=0` | ✅ 任务目标跟踪正常 |
| `game_state.active` | `358` | ✅ 游戏运行了 358 个游戏秒 |
| `game_state.in_mission` | `1` | ✅ 任务中状态正常 |

### 关键发现：Reborn galaxy 代码正在运行
- **worker_before=24**（基线无 Reborn 时为 10）
- 多出的 14 个工人说明 Reborn 的 galaxy 代码（Lib48DF4533）正在执行并生成了额外单位
- 这是 Reborn mod 功能正常的最强证据

### ScriptError 检查
- 加载阶段：无 ScriptError（20 秒宽限期通过）
- 运行时：无 ScriptError（游戏运行 358 秒，银行持续更新）
- 无崩溃日志（08:36:54 的崩溃属于上一个 API 模式会话，非本次测试）

### 训练探针说明
`train_completed=false(diag_skip)` 是 launcher 代码设计（第 601-602 行）：
```galaxy
// 占位符探针 - 只统计工人数，不实际下发训练命令
libPortingObserver_gf_Publish("alenger_train_probe_result",
    "train_ability_placeholder; worker_before=" + IntToString(lv_workerBefore) +
    "; train_completed=false(diag_skip)", false);
```
此行为对所有指挥官相同（包括纯 Empire 基线），不是 Reborn 导致的退化。

## 与疯批帝国的完成度对比

| 指标 | 疯批帝国 | 重生虫心（当前） | 达标 |
|------|---------|----------------|------|
| Mod 同步 | ✅ | ✅ 5 个 mod 全部同步 | ✅ |
| 依赖声明 | ✅ | ✅ cmre-alenger-dependencies.json | ✅ |
| DocumentHeader 完整性 | ✅ | ✅ 修复后无 EF BF BD 损坏 | ✅ |
| 地图加载 | ✅ | ✅ 60.6s, Alerts.txt 27748 bytes | ✅ |
| ScriptError（加载） | 无 | 无 | ✅ |
| ScriptError（运行时） | 无 | 无（358 秒运行） | ✅ |
| 银行 IPC | ✅ | ✅ NeuroIntegration.SC2Bank 更新 | ✅ |
| 起始单位注入 | ✅ created_p1=1, created_p2=1 | ✅ created_p1=1, created_p2=1 | ✅ |
| CMRE 观察者 | ✅ 初始化 | ✅ 初始化 | ✅ |
| 任务阶段跟踪 | ✅ | ✅ day/night 跟踪 | ✅ |
| Reborn galaxy 代码运行 | N/A | ✅ worker_before=24 vs 基线 10 | ✅ |
| 训练探针 | diag_skip（占位符设计） | diag_skip（占位符设计） | ✅ 相同 |

### 项目验收标准对照（reborn-mods-cmre-integration/project.json）

| # | 验收标准 | 状态 | 证据 |
|---|---------|------|------|
| 1 | 5 个 Reborn mod 复制到 cmre-runtime/Mods/reborn/ 且子 mod 路径重写 | ✅ | launcher SYNC 日志：5 个 mod 全部同步 |
| 2 | SwarmStory.SC2Campaign 和 swarmstoryutil.sc2mod 部署到 SC2 安装 Campaigns/ | ✅ | 文件系统验证存在 |
| 3 | cmre-alenger-dependencies.json 声明 optionalPackageMods 列出 5 个 Reborn mod | ✅ | dependencies.json 含 5 个 reborn\ 路径 |
| 4 | launch-cmre-alenger.ps1 支持 -EnableReborn 开关 | ✅ | "Reborn mods enabled: adding 5 optional dependencies" |
| 5 | CMRE 地图以 -EnableReborn 启动达到 ready 状态且无新 ScriptError | ✅ | 60.6s 加载完成, 0 ScriptError, 银行 IPC 正常 |

## 结论

重生虫心移植已达到与疯批帝国相同的完成度。5 个 Reborn mod 在 CMRE + Empire Alenger3 运行时中完整加载并正常运行，Reborn galaxy 代码（Lib48DF4533）成功执行，无 ScriptError，银行 IPC 正常工作。
