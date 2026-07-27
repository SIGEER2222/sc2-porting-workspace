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

## 与疯批帝国的完成度对比

| 指标 | 疯批帝国 | 重生虫心（当前） |
|------|---------|----------------|
| Mod 同步 | ✅ | ✅ 5 个 mod 全部同步 |
| 依赖声明 | ✅ | ✅ cmre-alenger-dependencies.json |
| 地图加载 | ✅ | ✅ 57.6s, Alerts.txt 31554 bytes |
| ScriptError | 无 | 无 |
| 银行 IPC | ✅ | ✅ NeuroIntegration.SC2Bank 更新 |
| 单位生产验证 | ✅ | 待验证（需进图手动测试） |

## 下一步
- 进图手动验证 Reborn 单位能否正常生产
- 如有 ScriptError，修复 galaxy 库冲突
- 验证 Reborn 特有机制（如虫心重生机制）是否正常工作
