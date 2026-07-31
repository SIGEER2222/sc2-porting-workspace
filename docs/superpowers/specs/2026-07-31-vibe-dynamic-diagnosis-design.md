# Vibe 动态诊断 MVP 设计（Stage 1）

## 日期
2026-07-31

## 背景与现状

Vibe 框架（[tools/galaxy-vibe/](file:///e:/Code/MyMod/SC2VibeTools/sc2-porting-workspace/tools/galaxy-vibe/)）已通过 P0 传输层、P1 REPL（14/15 PASS）、G3 战斗闭环（9/9 PASS）三项真机验收，具备 spawn/kill/set_vital/set_resource/query/visual 等 13 个 operation 的同步 RPC 能力。

但 Reborn 移植收尾（[docs/reborn-port-final-report.md](file:///e:/Code/MyMod/SC2VibeTools/sc2-porting-workspace/docs/reborn-port-final-report.md)）暴露了 Vibe 的关键缺口：
- **升级解锁能力**：无 `upgrade.*` / `tech_tree.*` handler，不能调 `SetUpgradeLevel` / `TechTreeUpgradeCount`
- **单位属性查询**：`query.units` 只返回 count，不能查 attack/armor/range/speed/attributes
- **即时反馈**：单次快照，无周期 state delta（但 MVP 阶段不需要）

Reborn 15 个指挥官的 Stage 03 验证遗留两个 ⚠️ 项：升级解锁未验证、TechTreeUpgradeCount 前置条件未验证。这两个缺口正好可由 Vibe 的动态能力补上，最终目标是用 Vibe 自动诊断并修复所有 mod 的 Catalog/Galaxy 缺陷。

## 目标与非目标

### 做（Stage 1 范围）
1. 扩展 Vibe Kernel，新增 3 个 operation：`upgrade.set_level`、`query.unit_attrs`、`tech_tree.check`
2. 新增 Python 诊断脚本 `vibe-diagnose.py`，跑通"reset → set_level → spawn → query_attrs → assert"闭环
3. 新增 Marine baseline 期望值表，在 vibe 测试地图上验证升级+属性诊断
4. 输出 PASS/FAIL 报告（JSON + Markdown）

### 不做（Stage 2/3 或不在范围）
- 生产面板查询（`query.trainable_units` / `query.production_queue`）— Stage 2
- 战斗断言扩展 — Stage 2（复用 G3）
- 载体切到 Reborn 真实 mod — Stage 2
- 根因定位（ScriptError 关联 + Catalog 缺陷定位）— Stage 3
- 自动 patch Galaxy/Catalog — Stage 3
- 周期 state delta 推送 — 不在 MVP 范围
- 修改单位非 vital 属性（攻击力/护甲/行为/owner/下指令）— 不在 MVP 范围

### 验收标准
在 `亡者之夜_vibe_live.SC2Map` 上跑 `vibe-diagnose.py --scenario marine-baseline.json`：
- `marine_base_armor` check：spawn Marine → query.unit_attrs.armor == 0 → **PASS**
- `marine_with_shield_wall` check：upgrade.set_level("ShieldWall", 1) → spawn Marine → query.unit_attrs.armor == 3 → tech_tree.check unlocked == 1 → **PASS**
- `marine_nonexistent_upgrade` check：upgrade.set_level("NonExistent", 1) → tech_tree.check unlocked == 0 → **FAIL（预期失败路径，验证 error_code 处理）**
- 全程无新增 ScriptError
- report.json + report.md 生成到 `artifacts/vibe-diagnose/<timestamp>/`

## 架构

```
vibe-diagnose.py (Python 侧)
   │
   ├─ VibeHost.request("scenario.reset", {})
   ├─ VibeHost.request("upgrade.set_level", {player:1, upgrade:"ShieldWall", level:1})
   ├─ VibeHost.request("unit.spawn", {unit_type:"Marine", count:1, player:1, x:50, y:50})
   ├─ VibeHost.request("query.unit_attrs", {unit_tag: <tag>})
   ├─ VibeHost.request("tech_tree.check", {player:1, upgrade:"ShieldWall"})
   └─ assert + 报告生成
                │
                ▼ (Bank RPC, 已有机制)
LibVibeKernel.galaxy (Galaxy 侧)
   ├─ HandleUpgradeSetLevel   (新增)
   ├─ HandleQueryUnitAttrs    (新增)
   └─ HandleTechTreeCheck     (新增)
```

复用现有 Bank RPC 三层结构（`section="request"` / `"response"` / `"index"`）、BankPoll 0.5s 触发器、Python 100ms 轮询 5s 超时机制。不改动 P0/P1 已验证的传输层。

## 组件设计

### A. Kernel 扩展

文件：[tools/galaxy-vibe/kernel/LibVibeKernel.galaxy](file:///e:/Code/MyMod/SC2VibeTools/sc2-porting-workspace/tools/galaxy-vibe/kernel/LibVibeKernel.galaxy) + [tools/galaxy-vibe/kernel/whitelist.json](file:///e:/Code/MyMod/SC2VibeTools/sc2-porting-workspace/tools/galaxy-vibe/kernel/whitelist.json)

新增 3 个 operation handler，在 `libVibeKernel_gf_Dispatch` 中分发：

| operation | Galaxy native 调用 | 参数 | 返回 payload |
|---|---|---|---|
| `upgrade.set_level` | `libNtve_gf_SetUpgradeLevelForPlayer(player, upgrade, level)` | `player`(1-15) / `upgrade`(字符串) / `level`(0-15) | `{applied:1}` |
| `query.unit_attrs` | `UnitGetType` + `UnitGetPropertyFixed`(life/maxlife/armor/energy/shield) + `CatalogFieldValueGet`(武器伤害/射程/属性词缀) | `unit_tag` | `{unit_type, life, max_life, armor, shield, energy, weapon_damage, weapon_range, attributes:[...]}` |
| `tech_tree.check` | `TechTreeUpgradeCount(player, upgrade, c_techCountCompleteOnly)` | `player` / `upgrade` | `{count: N, unlocked: 0/1}` |

**安全边界**：
- `upgrade` 参数走 whitelist 正则校验（`^[A-Za-z][A-Za-z0-9_]*$`），防注入
- `level` 限 0-15，超出返回 `INVALID_LEVEL`
- `player` 限 1-15，超出返回 `INVALID_PLAYER`
- `unit_tag` 必须为有效整数，null/0 返回 `UNIT_NOT_FOUND`
- 三个 operation 加入 `whitelist.json` 的 `allowed_operations`，未注册的一律 `UNKNOWN_OPERATION`

**`query.unit_attrs` 字段来源**：
- `unit_type`：`UnitGetType(unit)` 返回的字符串
- `life` / `max_life` / `shield` / `energy`：`UnitGetPropertyFixed(unit, c_unitPropLife/MaxLife/Shield/Energy, true)`
- `armor`：`CatalogFieldValueGet(c_gameCatalogUnit, UnitGetType(unit), "ArmorArray[0].Value", c_playerOrNone)` —— 注意 armor 受升级影响需用 player 上下文，实际用 `UnitGetPropertyFixed(unit, c_unitPropArmor, true)`（若该 native 可用，否则 fallback 到 Catalog）
- `weapon_damage` / `weapon_range`：`CatalogFieldValueGet` 读 `Weapons[0].DisplayEffect` → 再读 CEffectDamage 的 `Amount`，以及 `Weapons[0].Range`
- `attributes`：遍历 `AttributesArray` 读 `Light/Biological/Armored/Massive/Psionic/Mechanical` 等标签位

> 实施时若某些 Catalog 字段路径过长或不稳定，先返回能稳定拿到的字段（life/max_life/armor/shield/energy/unit_type），weapon/attributes 标注 `unavailable` 而非 crash。

### B. Python 诊断脚本

文件：`tools/galaxy-vibe/diagnose/vibe-diagnose.py`（新建）

```
vibe-diagnose.py --map <path> --scenario <expectations.json> [--port 8119] [--mod <path>]
  1. VibeHost.start_session() + connect_sc2(map_path=map)
  2. for each check in expectations.checks:
     a. VibeHost.request("scenario.reset", {})
     b. if check.upgrade: VibeHost.request("upgrade.set_level", {player, upgrade, level})
     c. resp = VibeHost.request("unit.spawn", {unit_type, count:1, player, x, y})
        spawned_tag = resp.payload.units[0].tag
     d. attrs = VibeHost.request("query.unit_attrs", {unit_tag: spawned_tag})
     e. if check.upgrade: tech = VibeHost.request("tech_tree.check", {player, upgrade})
     f. evaluate assert: for each (key, op, expected) in check.assert:
        - actual = attrs.payload[key] 或 tech.payload.unlocked
        - PASS if op(actual, expected) else FAIL
     g. record {check_name, status, actual, expected, error_code}
  3. 写 artifacts/vibe-diagnose/<timestamp>/report.json + report.md
  4. exit 0 if all PASS, exit 1 if any FAIL/ERROR
```

**assert op 支持**：`==`、`!=`、`>`、`<`、`>=`、`<=`、`contains`（用于 attributes）

**报告格式**：
- `report.json`：机器可读，schema 见下
- `report.md`：人可读表格（check_name / status / actual / expected / notes）

```json
{
  "schemaVersion": 1,
  "scenario": "marine-baseline",
  "timestamp": "2026-07-31T...",
  "map": "亡者之夜_vibe_live.SC2Map",
  "summary": { "total": 3, "pass": 2, "fail": 1, "error": 0 },
  "checks": [
    {
      "name": "marine_base_armor",
      "status": "PASS",
      "actual": { "armor": 0 },
      "expected": { "armor": "== 0" },
      "error_code": "OK"
    }
  ]
}
```

### C. 期望值表

文件：`tools/galaxy-vibe/diagnose/expectations/marine-baseline.json`（新建）

```json
{
  "scenario": "marine-baseline",
  "description": "验证 upgrade.set_level + query.unit_attrs + tech_tree.check 闭环",
  "checks": [
    {
      "name": "marine_base_armor",
      "unit_type": "Marine",
      "player": 1,
      "spawn_at": [50, 50],
      "assert": { "armor": "== 0" }
    },
    {
      "name": "marine_with_shield_wall",
      "unit_type": "Marine",
      "player": 1,
      "upgrade": "ShieldWall",
      "upgrade_level": 1,
      "spawn_at": [51, 50],
      "assert": { "armor": "== 3", "tech_tree_unlocked": true }
    },
    {
      "name": "marine_nonexistent_upgrade",
      "unit_type": "Marine",
      "player": 1,
      "upgrade": "NonExistent",
      "upgrade_level": 1,
      "spawn_at": [52, 50],
      "expect_status": "FAIL",
      "assert": { "tech_tree_unlocked": false }
    }
  ]
}
```

> `ShieldWall` 升级给 Marine +3 护甲是 SC2 标准 Catalog 行为，作为 baseline 验证载体。实施时若实际值不是 3（版本差异），以真机实测值为准调整期望值表，不视为设计缺陷。

## 数据流

1. Python `VibeHost.request` → 序列化为 `key=value;...` 字符串 → 写 Bank `section="request"` key=`<request_id>`
2. Galaxy `BankPoll` 触发器 0.5s 内检测 `index.pending_request_id` 变化 → `libVibeKernel_gf_Dispatch` → 命中 handler → 执行 native 调用 → 拼 JSON 响应 → 写 `section="response"` key=`<request_id>`
3. Python 100ms 轮询 `section="response"` key=`<request_id>`，5s 超时（已有机制，[vibe_host.py](file:///e:/Code/MyMod/SC2VibeTools/sc2-porting-workspace/tools/galaxy-vibe/host/vibe_host.py) 的 `request()`）
4. assert 失败 → 记录 actual vs expected → 继续下一 check（不中断流程）
5. 全部 check 跑完 → 生成 report.json + report.md → 退出码 0/1

## 错误处理

| 错误类型 | 表现 | 处理 |
|---|---|---|
| Kernel handler 失败 | `error_code != "OK"` | Python 记录 `status: "ERROR"`，不算 FAIL，继续下一 check |
| upgrade 不存在 | `SetUpgradeLevelForPlayer` 静默无效 → `tech_tree.check` 返回 `unlocked:0` | assert `tech_tree_unlocked == true` → FAIL（能定位"升级未生效"） |
| 单位 spawn 失败 | spawn 响应 `units` 为空 | query.unit_attrs 跳过，记录 `status: "ERROR"` |
| Bank 超时（5s） | 拿不到响应 | 记录 `status: "ERROR", notes: "Bank timeout, check Kernel compilation"` |
| `query.unit_attrs` 部分字段不可用 | payload 中该字段为 `"unavailable"` | 若该字段在 assert 中 → ERROR；否则忽略 |

## 测试策略

### 离线测试
扩展 [tools/galaxy-vibe/tests/test_kernel.py](file:///e:/Code/MyMod/SC2VibeTools/sc2-porting-workspace/tools/galaxy-vibe/tests/test_kernel.py)：
- 新增 3 个 operation 的 whitelist 契约测试（参数校验、合法/非法值）
- Galaxy 语法静态检查（确保新 handler 编译通过）
- RPC 序列化测试（请求/响应 round-trip）

### 真机测试
- `vibe-diagnose.py --scenario marine-baseline.json` 在 `亡者之夜_vibe_live.SC2Map` 上跑
- 期望：marine_base_armor=PASS、marine_with_shield_wall=PASS、marine_nonexistent_upgrade=FAIL（预期失败路径）
- 复核 `C:\Users\22448\Documents\StarCraft II\GameLogs` 无新增 ScriptError
- 启动用 [launch-galaxy-vibe.ps1](file:///e:/Code/MyMod/SC2VibeTools/sc2-porting-workspace/tools/galaxy-vibe/launch-galaxy-vibe.ps1) `-Repl` 模式，依赖 Wait-GameReady 信号，禁止固定时间盲等

### fail 路径验证
- 故意传 `upgrade:"NonExistent"` → 期望 FAIL 或 ERROR（非 crash）
- 故意传 `level:99` → 期望 `error_code: "INVALID_LEVEL"`
- 故意传 `player:99` → 期望 `error_code: "INVALID_PLAYER"`

## 文件清单（Stage 1 写范围）

| 文件 | 操作 | 说明 |
|---|---|---|
| `tools/galaxy-vibe/kernel/LibVibeKernel.galaxy` | 修改 | 新增 3 个 handler + Dispatch 分发 |
| `tools/galaxy-vibe/kernel/whitelist.json` | 修改 | 新增 3 个 allowed_operations |
| `tools/galaxy-vibe/diagnose/vibe-diagnose.py` | 新建 | 诊断脚本 |
| `tools/galaxy-vibe/diagnose/expectations/marine-baseline.json` | 新建 | Marine baseline 期望值表 |
| `tools/galaxy-vibe/tests/test_kernel.py` | 修改 | 扩展离线测试 |
| `artifacts/vibe-diagnose/<timestamp>/report.json` | 生成 | 真机运行产物 |
| `artifacts/vibe-diagnose/<timestamp>/report.md` | 生成 | 真机运行产物 |

不改动：P0/P1 传输层、launch-galaxy-vibe.ps1、vibe_host.py 核心（仅 import 使用）、galaxy_repl.py。

## Stage 2/3 演进路径（不在本次实施）

### Stage 2：生产面板 + Reborn 真实 mod
- 新增 `query.trainable_units`（Catalog + requirement validator 解析建筑可生产单位）
- 新增 `query.production_queue`（`UnitQueueGetProperty` 读当前队列）
- 诊断脚本扩展生产面板检查
- 载体切到 Reborn 真实 mod（launch-cmre-alenger.ps1），验证 15 指挥官特有单位是否在生产面板

### Stage 3：根因定位 + 自动 patch
- ScriptError 关联（将 ScriptError 文本与 fail check 关联）
- Catalog/Galaxy 缺陷定位（指出哪个文件/函数/行号缺失）
- 自动 patch（补 BankList 授权、修 include 顺序、补 SetUpgradeLevel 调用），需备份/回滚/安全边界

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| `query.unit_attrs` 的 weapon/attributes 字段 Catalog 路径不稳定 | 先返回稳定字段，不稳定字段标 `unavailable` 不 crash |
| `UnitGetPropertyFixed(c_unitPropArmor)` 可能返回基础值不含升级加成 | 实施时实测，若不含则 fallback 到 Catalog 读 `ArmorArray` + 升级 `ModificationArray` |
| Marine + ShieldWall 实际护甲值与期望 3 不符 | 以真机实测值为准调整期望值表 |
| Kernel 重新编译需 Galaxy Editor 手动重存（冷循环已知限制） | Stage 1 用已有 vibe 测试地图的 Kernel 集成流程，不依赖冷循环自动编译 |
| Bank RPC 0.5s 延迟影响诊断速度 | 可接受，MVP 不追求高频；Stage 2 若需提速再考虑 chat 通道触发 |

## 依赖

- 现有 Vibe Kernel 机制（[LibVibeKernel.galaxy](file:///e:/Code/MyMod/SC2VibeTools/sc2-porting-workspace/tools/galaxy-vibe/kernel/LibVibeKernel.galaxy)）
- 现有 VibeHost 封装（[vibe_host.py](file:///e:/Code/MyMod/SC2VibeTools/sc2-porting-workspace/tools/galaxy-vibe/host/vibe_host.py)）
- 现有启动器（[launch-galaxy-vibe.ps1](file:///e:/Code/MyMod/SC2VibeTools/sc2-porting-workspace/tools/galaxy-vibe/launch-galaxy-vibe.ps1)）
- vibe 测试地图（`亡者之夜_vibe_live.SC2Map`，已集成 Kernel）
- SC2 Catalog natives（`TechTreeUpgradeCount` / `libNtve_gf_SetUpgradeLevelForPlayer` / `UnitGetPropertyFixed` / `CatalogFieldValueGet`）
