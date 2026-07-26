# SC2 单位平衡分析工具设计文档

**日期**：2026-07-26
**状态**：已确认，进入实现阶段
**目标**：提取 12 起义指挥官 + 18 官方指挥官所有单位数值，按平衡公式评分，输出离群报告与补丁建议（不直接应用到 mod）

---

## 1. 平衡公式（v4 最终版）

### 1.1 公式总览

```
# 1. 装甲类型 DPS 矩阵
DPS[armor_type] = Σ (Damage + Bonus[armor_type]) / Period × splash_factor

# 2. 多场景价值
V_general      = (DPS_general × EHP × range_factor + Skill_value) × role_modifier
V_vs_light     = (DPS_Light × EHP × range_factor + Skill_value) × role_modifier × splash_factor
V_vs_armored   = (DPS_Armored × EHP × range_factor + Skill_value) × role_modifier
V_vs_air       = (DPS_Air × EHP × range_factor + Skill_value) × role_modifier
V_vs_massive   = (DPS_Massive × EHP × range_factor + Skill_value) × role_modifier
V_tank         = (EHP × range_factor × 0.3 + Skill_value × 0.5) × role_modifier

# 3. 评分
S_scenario = V_scenario / C_normalized
S = max(S_general, max(S_specialized) × 0.85, S_tank × 0.85)

# 4. 离群
z_internal = (S - μ_group) / σ_group                    # 起义内部按种族+定位分组
z_official = (S - μ_official_group) / σ_official_group  # vs 官方 18 指挥官同档位

# 5. 克制矩阵（简化版，输出 Top 10 极端克制）
Counter: max over (attacker, defender) of DPS_vs_defender / (EHP_defender / C_attacker)
```

### 1.2 兵种定位识别（第 0 层）

| 定位标签 | 判定条件 | 依据 |
|---------|---------|------|
| `splash` | 任一武器 `AreaArray.Radius > 1.0` | SC2 WeaponData 字段定义 |
| `anti_light` | `DPS_vs_Light > DPS_vs_general × 1.5` | 1.5 倍阈值参考 Marauder/Stalker 加成比例 |
| `anti_armored` | `DPS_vs_Armored > DPS_vs_general × 1.5` | 同上 |
| `anti_air` | `DPS_vs_Air > 0 AND DPS_vs_Ground ≤ 10% × DPS_vs_Air` | Viking/Goliath 专用模式 |
| `anti_massive` | `DPS_vs_Massive > DPS_vs_general × 1.5` | 对 Boss 类加成 |
| `tank` | `EHP/C > μ × 1.5 AND DPS/C < μ × 0.6` | 高血低伤为肉盾定义 |
| `generalist` | 不满足以上任一 | 通用单位 |

一个单位可同时持有多个标签（如 Thor = anti_air + anti_light）。

### 1.3 成本归一化

```
C_normalized = Minerals + 3 × Vespene + 0.5 × Supply² + 0.05 × BuildTime
```

| 项 | 系数 | 依据 | 信源 |
|----|------|------|------|
| Minerals | 1.0 | 基准 | - |
| Vespene | 3.0 | 瓦斯采集效率约 1/3 矿物 | SC2 官方采集机制 + ares-sc2 cost_dict.py 隐含比 |
| Supply² | 0.5 | 兰彻斯特平方律：N 个小单位战力 ∝ N²，大单位等效造价二次上升 | [Lanchester's Laws (1916)](https://en.wikipedia.org/wiki/Lanchester%27s_laws)；SC2 patch 中大单位（BC/Carrier）反复加技能补偿 |
| BuildTime | 0.05/秒 | 1 秒约值 0.05 矿物（参考 SCV 50 矿/12s = 4.2/s，因并发建造取 1%） | SC2 BuildTime 数据反推 |

### 1.4 DPS_eff

```
DPS_eff = Σ_i (Damage_i + Bonus[armor_type]) / Period_i × splash_factor_i
```

- 多武器叠加（如 Battlecruiser 多炮塔）
- `splash_factor` 分档：

| AoE 半径 | splash_factor | 典型单位 |
|---------|--------------|---------|
| ≤ 1.0 | 1.0 | 单体（Marine） |
| 1.0 - 2.0 | 1.15 | 小范围溅射（Baneling） |
| 2.0 - 3.5 | 1.30 | 中范围（Siege Tank） |
| > 3.5 | 1.45 | 大范围（Colossus 横扫） |

依据：合作模式 AoE 单位平均命中 1.5-3 个目标，对应 15%-45% 有效伤害提升。

### 1.5 EHP

```
EHP = (LifeMax + ShieldsMax) × (1 + 0.05 × LifeArmor) × structure_penalty
structure_penalty = Structure属性 ? 0.6 : 1.0
```

- 0.05/护甲：SC2 每点护甲减 1 伤害，对平均 20 伤害/击 ≈ 5% 减伤
- Structure ×0.6：建筑不可移动、易被集火，参考 SC2 patch 中建筑多次加强 HP

### 1.6 range_factor

```
range_factor = 1 + 0.05 × max(0, max_Range - 3)
```

- 0.05/射程：从 SC2 patch 历史反推（Marine 射程 5 → 加 1 射程升级价值约 +10%）
- 与社区"射程+1 ≈ +5-8%"经验值对齐

### 1.7 Skill_value

| 技能类型 | 评分 | 依据 |
|---------|------|------|
| 主动伤害 | (伤害/冷却) × 0.5 | 加入等效 DPS，0.5 折价因有冷却 |
| 主动控制 | +30 | Statis/Fungal 类硬控参考 Infestor 调整史 |
| 位移 | +25 | Blink/Viking 形态切换 |
| 召唤 | 召唤物 EHP × 0.1 | Brood Lord、Swarm Host |
| 治疗/护盾 | (治疗量/冷却) × 0.3 | Medic、Shield Battery |
| 光环 | 影响单位数 × 增益系数 × 10 | 经验值，无公开公式 |
| 隐身 | +50 | Cloak 在 SC2 中价值约 1 个升级 |
| 复活 | +80 | Reanimators 突变因子价值 |

数据来源：解析 `AbilData.xml`（ability 的 cooldown/duration）+ `EffectData.xml`（ability 关联的 effect）+ `BehaviorData.xml`（buff 数值）。

### 1.8 role_modifier（自身空/地 + 对空/对地）

| 自身 plane | 对地 | 对空 | modifier | 依据 |
|-----------|------|------|----------|------|
| Ground | ✓ | ✗ | 1.0 | 基准 |
| Ground | ✓ | ✓ | 1.05 | 双攻 Goliath/Marine |
| Air | ✓ | ✗ | 1.10 | 空军对地压制（无地形） |
| Air | ✗ | ✓ | 1.05 | 空战专用 Viking |
| Air | ✓ | ✓ | 1.20 | 全能 BC，参考 SC2 多次加强 |
| Hero | - | - | 0.5 | 英雄造价远超线性，独立档位 |
| Worker | - | - | 0.3 | 经济单位非战斗 |
| Structure | - | - | 0.5 | 已含 structure_penalty，避免双重减 |

依据：SC2 patch 历史中空军反复被加建造时间/造价，体现其结构性优势。

### 1.9 多场景评分（核心）

不输出单一 V_base，而是输出**场景化价值矩阵**：

| 场景 | 公式 | 适用场景 |
|------|------|---------|
| `V_general` | `(DPS_general × EHP × range_factor + Skill_value) × role_modifier` | 对无加成目标的通用价值 |
| `V_vs_light` | `(DPS_Light × EHP × range_factor + Skill_value) × role_modifier × splash_factor` | 对轻甲杂兵（含 AoE 加成） |
| `V_vs_armored` | `(DPS_Armored × EHP × range_factor + Skill_value) × role_modifier` | 对重甲单位 |
| `V_vs_air` | `(DPS_Air × EHP × range_factor + Skill_value) × role_modifier` | 对空军 |
| `V_vs_massive` | `(DPS_Massive × EHP × range_factor + Skill_value) × role_modifier` | 对 Boss/巨型 |
| `V_tank` | `(EHP × range_factor × 0.3 + Skill_value × 0.5) × role_modifier` | 肉盾价值（DPS 权重降到 0.3） |

**最终评分**：

```
S = max(
    S_general,                                          # 通用场景
    max(S_vs_light, S_vs_armored, S_vs_air, S_vs_massive) × 0.85,  # 专精场景折价 15%
    S_tank × 0.85                                       # 肉盾场景折价
)
```

**专精折价 0.85 的依据**：Sirlin《Balancing Multiplayer Games》"对手博弈性"——专精单位在对手不出对应兵种时价值归零，15% 折价体现"专精风险溢价"。数值参考 SC2 patch 历史中专精单位（如 Viking）通常比通用单位（如 Marine）性价比低 10-20%。

### 1.10 离群判定 + 基准锚定

```
z_internal = (S - μ_group) / σ_group                    # 起义内部按种族+定位分组
z_official = (S - μ_official_group) / σ_official_group  # vs 官方 18 指挥官同档位
```

- |z| > 2 → 离群
- 起义整体偏移 `Δ_global = μ_起义 - μ_官方`，作为起义整体强弱判定
- 分组维度：种族（Terran/Protoss/Zerg）× 定位（splash/anti_light/anti_armored/anti_air/tank/generalist）

### 1.11 克制矩阵（简化版）

```typescript
interface CounterRelation {
  attacker: string;
  defender: string;
  efficiency: number;  // = DPS_attacker_vs_defender / (EHP_defender / C_attacker)
  severity: 'extreme' | 'strong' | 'normal';
}
```

输出：
1. 每个单位的最强克制对象（每个单位 1 条）
2. 全局 Top 10 极端克制关系（efficiency > 3σ 标为 extreme）

---

## 2. 工具架构

### 2.1 模块划分

```
sc2-porting-workspace/tools/balance/
├── src/
│   ├── catalog/
│   │   ├── xml-parser.mjs          # 行级正则解析 XML 字段（继承 analyze-catalog.mjs 风格）
│   │   ├── parent-resolver.mjs     # 处理 parent 继承链合并
│   │   └── effect-tracer.mjs       # Weapon → Effect → Damage 链路追踪
│   ├── metrics/
│   │   ├── unit-metrics.mjs        # 提取单位数值（HP/Armor/Cost/Speed/Attr）
│   │   ├── weapon-metrics.mjs      # 提取武器 DPS / AoE / Period / TargetFilters
│   │   ├── effect-metrics.mjs      # 提取 Effect 链伤害（递归 set/damage/search）
│   │   └── behavior-classifier.mjs # 识别隐身/召唤/治疗/控制等机制
│   ├── scoring/
│   │   ├── formula.mjs             # 第 1-3 层公式
│   │   ├── outlier.mjs             # z-score 离群判定
│   │   ├── counter-matrix.mjs      # 克制矩阵
│   │   └── baseline.mjs            # 官方基准锚定
│   ├── reports/
│   │   ├── json-reporter.mjs       # JSON 结构化报告
│   │   └── md-reporter.mjs         # Markdown 可读报告
│   └── index.mjs                   # CLI 入口
├── config/
│   ├── commanders.json             # 指挥官 → mod 路径映射
│   └── formula-weights.json        # 公式权重（可调，便于迭代）
└── package.json
```

### 2.2 数据流

```
[12 起义 mod + 官方 starcoop]
    ↓ (xml-parser + parent-resolver)
[NormalizedUnit[]]  ← 含完整字段值
    ↓ (effect-tracer + weapon-metrics)
[UnitWithDPS[]]     ← 含 DPS/AoE/TargetFilters
    ↓ (behavior-classifier)
[UnitWithMechanics[]] ← 含机制标签
    ↓ (formula.mjs)
[UnitScore[]]       ← 含 V_base / S / z-score
    ↓ (baseline + counter-matrix)
[PatchSuggestion[]] ← 最终补丁建议
    ↓ (reporters)
[report.json + report.md]
```

### 2.3 CLI 接口

```bash
# 全流程
node tools/balance/src/index.mjs analyze --all

# 仅提取数值
node tools/balance/src/index.mjs extract --commander Alenger3

# 仅评分
node tools/balance/src/index.mjs score --input units-raw.json

# 仅离群分析
node tools/balance/src/index.mjs outliers --input units-scored.json
```

### 2.4 输出位置

按 AGENTS.md "Put generated reports... under artifacts/" 规则：

```
sc2-porting-workspace/artifacts/balance/
└── 2026-07-26/
    ├── units-raw.json           # 提取的所有单位原始数值
    ├── units-scored.json        # 含 V_base/S/z 评分
    ├── outliers.json            # 离群单位清单
    ├── baseline-official.json   # 官方基准统计
    ├── counter-matrix.json      # 克制关系
    ├── patch-suggestions.json   # 补丁建议
    ├── report.md                # 人可读报告
    └── formula-weights.json     # 本次使用的权重（可复现）
```

---

## 3. 信源汇总

| 信源 | 用于 |
|------|------|
| [Lanchester's Laws (1916)](https://en.wikipedia.org/wiki/Lanchester%27s_laws) | 平方律 → Supply² 成本 |
| [Sirlin《Balancing Multiplayer Games》](https://www.sirlin.net/articles/balancing-multiplayer-games-part-4-intuition) | 专精折价 0.85、克制链理念 |
| SC2 官方 GameData XML | 字段定义、装甲加成机制 |
| docs/kb-sources/catalog/fields-reference.md | Unit/Weapon/Effect 字段语义 |
| docs/kb-sources/catalog/targeting.md | TargetFilters 解析规则 |
| ares-sc2 cost_dict.py | 矿气比参考 |
| python-sc2 game_data.py | Cost/TechAlias 计算参考 |
| [SC2 patch notes 历史](https://starcraft2.blizzard.com/en-us/news/patch-notes/) | 射程/护甲/空军溢价经验值 |

---

## 4. 适用与不适用场景

### 4.1 适用

- ✅ **合作模式指挥官平衡**（本次目标）：起义 vs 官方，按"种族+定位"分组离群
- ✅ **自定义 mod 单位平衡审计**：识别离群单位
- ✅ **新单位定价参考**：给定战力反推合理造价

### 4.2 不适用

- ❌ **PvP 对战平衡**：需扩展到完整克制矩阵 + 对局模拟，首版不做
- ❌ **战役难度调整**：战役是 PVE，敌方单位非玩家可控
- ❌ **Build Order 优化**：属于策略层，非单位层

### 4.3 已知限制（Caveats）

- 公式**不考虑微操收益**（如 Marine 散枪兵），高上限单位会被低估
- 公式**不模拟资源采集速率**，"早期单位"和"后期单位"的造价权重相同（首版不做时间价值折现）
- 公式**不计算科技树成本**，"需要 5 级科技"的单位会被高估（科技成本未计入）
- 公式**不处理 Behavior 复杂 Buff 链**（如叠加层数动态计算），首版只识别机制标签
- 公式**不评估指挥官技能/大招**，首版聚焦常驻单位

这些限制会在生成的报告中明确写出。

---

## 5. 实现策略

### 5.1 实现语言

**使用 .mjs（Node.js 原生 ES Modules）**，而非 TS。理由：
- 与现有 `tools/analysis/analyze-catalog.mjs` 风格一致
- 无需编译步骤，可直接 `node` 执行
- 减少首版工具的实现复杂度

### 5.2 解析策略

**行级正则解析**，而非 DOM 解析。理由：
- SC2 XML 字段格式固定（`<Field value="..."/>` 或 `<Field>...</Field>`）
- 正则比 DOM 解析快 10×，且能处理嵌套
- 与 analyze-catalog.mjs 一致

### 5.3 parent 继承

递归合并，子覆盖父。SC2 catalog 标准继承语义。

### 5.4 Effect 链追踪

深度优先，最多 8 层，识别环。SC2 effect set 可嵌套但实际深度有限。

---

## 6. 不做的事（YAGNI）

- 不写 .SC2Mod 补丁文件（用户已说先不应用）
- 不做运行时数值验证（启动游戏成本不匹配首版目标）
- 不解析 Behavior 的复杂 Buff 链
- 不做 Build Order 优化
- 不做指挥官技能/大招评分
- 不做地图维度修正（首版仅全局离群判定）
