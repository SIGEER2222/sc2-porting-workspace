// src/reporter.mjs
// 输出 JSON + Markdown 报告。
//
// JSON 输出：
//   units-raw.json
//   units-scored.json
//   outliers.json
//   baseline-official.json
//   counter-matrix.json
//   patch-suggestions.json
//   formula-weights.json
// Markdown 输出：
//   report.md

import { mkdir, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";

// 把单位对象按 commander 分组序列化为 units-raw.json
export async function writeUnitsRaw(units, outputDir) {
  const byCommander = new Map();
  for (const u of units) {
    if (!byCommander.has(u.commander)) byCommander.set(u.commander, []);
    byCommander.get(u.commander).push(serializeUnitRaw(u));
  }
  const obj = {
    schema_version: 1,
    generated_at: new Date().toISOString(),
    commanders: {}
  };
  for (const [cmdr, arr] of [...byCommander.entries()].sort()) {
    obj.commanders[cmdr] = arr.sort((a, b) => a.id.localeCompare(b.id));
  }
  await writeJson(join(outputDir, "units-raw.json"), obj);
}

// 单位原始指标序列化（不含 z-score）
function serializeUnitRaw(u) {
  return {
    id: u.id,
    race: u.race,
    source: u.source,
    life_max: u.life_max,
    life_armor: u.life_armor,
    shields_max: u.shields_max,
    speed: u.speed,
    minerals: u.minerals,
    vespene: u.vespene,
    supply: u.supply,
    build_time: u.build_time,
    cost_normalized: u.cost_normalized,
    is_armored: u.is_armored,
    is_light: u.is_light,
    is_biological: u.is_biological,
    is_massive: u.is_massive,
    is_structure: u.is_structure,
    is_hero: u.is_hero,
    is_worker: u.is_worker,
    is_air: u.is_air,
    is_ground: u.is_ground,
    weapon_count: u.weapon_count,
    weapons: u.weapons,
    dps_general: u.dps_general,
    dps_light: u.dps_light,
    dps_armored: u.dps_armored,
    dps_massive: u.dps_massive,
    dps_air: u.dps_air,
    dps_ground: u.dps_ground,
    max_range: u.max_range,
    max_splash_radius: u.max_splash_radius,
    ehp: u.ehp,
    range_factor: u.range_factor,
    role_modifier: u.role_modifier,
    skill_value: u.skill_value,
    matched_skills: u.matched_skills,
    behavior_links: u.behavior_links,
    abil_links: u.abil_links
  };
}

export async function writeUnitsScored(unitsWithZ, outputDir) {
  const obj = {
    schema_version: 1,
    generated_at: new Date().toISOString(),
    units: unitsWithZ.map((u) => ({
      id: u.id,
      commander: u.commander,
      race: u.race,
      primary_role: u.primary_role,
      roles: u.roles,
      is_hero: u.is_hero,
      is_structure: u.is_structure,
      is_air: u.is_air,
      cost_normalized: u.cost_normalized,
      minerals: u.minerals,
      vespene: u.vespene,
      life_max: u.life_max,
      shields_max: u.shields_max,
      life_armor: u.life_armor,
      ehp: u.ehp,
      dps_general: u.dps_general,
      max_range: u.max_range,
      role_modifier: u.role_modifier,
      skill_value: u.skill_value,
      V_general: u.V_general,
      V_vs_light: u.V_vs_light,
      V_vs_armored: u.V_vs_armored,
      V_vs_air: u.V_vs_air,
      V_vs_massive: u.V_vs_massive,
      V_tank: u.V_tank,
      S_general: u.S_general,
      S_vs_light: u.S_vs_light,
      S_vs_armored: u.S_vs_armored,
      S_vs_air: u.S_vs_air,
      S_vs_massive: u.S_vs_massive,
      S_tank: u.S_tank,
      S: u.S,
      primary_scenario: u.primary_scenario,
      group_key: u.group_key,
      group_mu: u.group_mu,
      group_sigma: u.group_sigma,
      group_n: u.group_n,
      z_internal: u.z_internal,
      z_official: u.z_official
    }))
  };
  await writeJson(join(outputDir, "units-scored.json"), obj);
}

export async function writeOutliers(outliers, outputDir) {
  const obj = {
    schema_version: 1,
    generated_at: new Date().toISOString(),
    threshold: 2.0,
    count: outliers.length,
    outliers: outliers.map((o) => ({
      id: o.id,
      commander: o.commander,
      race: o.race,
      primary_role: o.primary_role,
      roles: o.roles,
      S: o.S,
      cost_normalized: o.cost_normalized,
      ehp: o.ehp,
      dps_general: o.dps_general,
      z_internal: o.z_internal,
      z_official: o.z_official,
      max_z: o.max_z,
      primary_scenario: o.primary_scenario
    }))
  };
  await writeJson(join(outputDir, "outliers.json"), obj);
}

export async function writeBaselineOfficial(groupStats, totalUnits, outputDir) {
  const obj = {
    schema_version: 1,
    generated_at: new Date().toISOString(),
    total_units: totalUnits,
    groups: Object.entries(groupStats).map(([key, stat]) => ({
      group_key: key,
      race: key.split("::")[0],
      role: key.split("::")[1],
      mu: stat.mu,
      sigma: stat.sigma,
      n: stat.n
    }))
  };
  await writeJson(join(outputDir, "baseline-official.json"), obj);
}

export async function writeCounterMatrix(matrix, outputDir) {
  const obj = {
    schema_version: 1,
    generated_at: new Date().toISOString(),
    severity_thresholds: matrix.severity_thresholds,
    per_attacker: matrix.per_attacker,
    top_n: matrix.top_n
  };
  await writeJson(join(outputDir, "counter-matrix.json"), obj);
}

export async function writePatchSuggestions(patches, outputDir) {
  const obj = {
    schema_version: 1,
    generated_at: new Date().toISOString(),
    count: patches.length,
    formula: "suggested_cost = current_cost × clamp(1 / (1 + 0.15 × z), 0.7, 1.3)",
    patches
  };
  await writeJson(join(outputDir, "patch-suggestions.json"), obj);
}

export async function writeFormulaWeights(weights, outputDir) {
  const obj = {
    schema_version: 1,
    generated_at: new Date().toISOString(),
    ...weights
  };
  await writeJson(join(outputDir, "formula-weights.json"), obj);
}

// Markdown 报告
export async function writeReportMarkdown({
  outputDir,
  alengerUnitCount,
  officialUnitCount,
  totalUnits,
  groupStatsAlenger,
  groupStatsOfficial,
  deltaGlobal,
  outliers,
  counterMatrix,
  patches,
  weights
}) {
  const lines = [];
  lines.push(`# SC2 单位平衡分析报告`);
  lines.push("");
  lines.push(`**生成时间**：${new Date().toISOString()}`);
  lines.push(`**工具版本**：balance tool v1 (公式 v4)`);
  lines.push(`**数据源**：12 起义指挥官 mod + 官方 starcoop 共享 mod（含 Mengsk / Stetmann 独立 mod）`);
  lines.push("");
  lines.push("## 1. 执行摘要");
  lines.push("");
  lines.push(`- 起义指挥官提取单位数：**${alengerUnitCount}**`);
  lines.push(`- 官方基准池单位数：**${officialUnitCount}**（合并 starcoop 共享 mod + Mengsk/Stetmann 独立 mod，不按指挥官区分）`);
  lines.push(`- 单位总数：**${totalUnits}**`);
  lines.push(`- 离群单位数（|z| > ${weights.outlier.z_threshold}）：**${outliers.length}**`);
  lines.push(`- 起义整体偏移 Δ_global = μ_起义 - μ_官方 = **${formatNum(deltaGlobal, 4)}**`);
  lines.push(`  - ${deltaGlobal > 0 ? "起义整体偏强（起义单位性价比显著高于官方基准）" : "起义整体偏弱"}（首版仅参考，起义作为自定义强力单位偏强是预期现象）`);
  lines.push("");

  lines.push("## 2. 公式说明");
  lines.push("");
  lines.push("### 2.1 核心公式（v4）");
  lines.push("");
  lines.push("```");
  lines.push("DPS[armor_type] = Σ (Damage + Bonus[armor_type]) / Period × splash_factor");
  lines.push("EHP = (LifeMax + ShieldsMax) × (1 + 0.05 × LifeArmor) × (Structure ? 0.6 : 1.0)");
  lines.push("range_factor = 1 + 0.05 × max(0, max_Range - 3)");
  lines.push("C_normalized = Minerals + 3 × Vespene + 0.5 × Supply² + 0.05 × BuildTime");
  lines.push("V_general = (DPS_general × EHP × range_factor + Skill_value) × role_modifier");
  lines.push("V_tank = (EHP × range_factor × 0.3 + Skill_value × 0.5) × role_modifier");
  lines.push("S_scenario = V_scenario / C_normalized");
  lines.push("S = max(S_general, max(S_specialized) × 0.85, S_tank × 0.85)");
  lines.push("z_internal = (S - μ_group) / σ_group  // 按种族+定位分组");
  lines.push("```");
  lines.push("");
  lines.push("### 2.2 兵种定位识别");
  lines.push("");
  lines.push("| 定位 | 判定条件 |");
  lines.push("|------|----------|");
  lines.push("| splash | 任一武器 AoE 半径 > 1.0 |");
  lines.push("| anti_light | DPS_Light > DPS_general × 1.5 |");
  lines.push("| anti_armored | DPS_Armored > DPS_general × 1.5 |");
  lines.push("| anti_air | DPS_Air > 0 AND DPS_Ground ≤ 10% × DPS_Air |");
  lines.push("| anti_massive | DPS_Massive > DPS_general × 1.5 |");
  lines.push("| tank | EHP/C > μ × 1.5 AND DPS/C < μ × 0.6 |");
  lines.push("| generalist | 不满足以上任一 |");
  lines.push("");

  lines.push("### 2.3 splash_factor 分档");
  lines.push("");
  lines.push("| AoE 半径 | splash_factor | 典型单位 |");
  lines.push("|---------|--------------|---------|");
  lines.push("| ≤ 1.0 | 1.00 | 单体（Marine） |");
  lines.push("| 1.0 - 2.0 | 1.15 | 小范围溅射（Baneling） |");
  lines.push("| 2.0 - 3.5 | 1.30 | 中范围（Siege Tank） |");
  lines.push("| > 3.5 | 1.45 | 大范围（Colossus 横扫） |");
  lines.push("");

  lines.push("### 2.4 role_modifier");
  lines.push("");
  lines.push("| 自身 plane | 对地 | 对空 | modifier |");
  lines.push("|-----------|------|------|----------|");
  lines.push("| Ground | ✓ | ✗ | 1.00 |");
  lines.push("| Ground | ✓ | ✓ | 1.05 |");
  lines.push("| Air | ✓ | ✗ | 1.10 |");
  lines.push("| Air | ✗ | ✓ | 1.05 |");
  lines.push("| Air | ✓ | ✓ | 1.20 |");
  lines.push("| Hero | - | - | 0.50 |");
  lines.push("| Worker | - | - | 0.30 |");
  lines.push("| Structure | - | - | 0.50 |");
  lines.push("");

  lines.push("### 2.5 Skill_value（首版简化）");
  lines.push("");
  lines.push("首版仅基于单位 ID 与 BehaviorArray Link 名字做启发式识别，不深度解析 AbilData。");
  lines.push("");
  lines.push("| 关键词 | 加分 |");
  lines.push("|-------|------|");
  for (const [k, v] of Object.entries(weights.skill_value)) {
    lines.push(`| ${k} | +${v} |`);
  }
  lines.push("");
  lines.push("其他技能不识别，skill_value=0；详见 Caveats。");
  lines.push("");

  lines.push("## 3. 整体对比（起义 vs 官方）");
  lines.push("");
  lines.push("### 3.1 分组统计（按 race × role）");
  lines.push("");
  lines.push("#### 起义指挥官");
  lines.push("");
  lines.push("| 分组 | μ (S) | σ | n |");
  lines.push("|------|--------|---|---|");
  for (const [key, stat] of Object.entries(groupStatsAlenger).sort()) {
    lines.push(`| ${key} | ${formatNum(stat.mu, 4)} | ${formatNum(stat.sigma, 4)} | ${stat.n} |`);
  }
  lines.push("");
  lines.push("#### 官方指挥官");
  lines.push("");
  lines.push("| 分组 | μ (S) | σ | n |");
  lines.push("|------|--------|---|---|");
  for (const [key, stat] of Object.entries(groupStatsOfficial).sort()) {
    lines.push(`| ${key} | ${formatNum(stat.mu, 4)} | ${formatNum(stat.sigma, 4)} | ${stat.n} |`);
  }
  lines.push("");

  lines.push("## 4. 离群单位 Top 10（按 |z| 降序）");
  lines.push("");
  lines.push("| 排名 | ID | 指挥官 | 种族 | 主定位 | S | cost | z_internal | z_official | max_z | 场景 |");
  lines.push("|------|-----|--------|------|--------|---|------|------------|------------|-------|------|");
  const top10 = outliers.slice(0, 10);
  top10.forEach((o, i) => {
    lines.push(`| ${i + 1} | ${o.id} | ${o.commander} | ${o.race} | ${o.primary_role} | ${formatNum(o.S, 4)} | ${formatNum(o.cost_normalized, 0)} | ${formatNum(o.z_internal, 2)} | ${formatNum(o.z_official, 2)} | ${formatNum(o.max_z, 2)} | ${o.primary_scenario} |`);
  });
  lines.push("");

  lines.push("## 5. 克制关系 Top 10（按 efficiency 降序）");
  lines.push("");
  lines.push("| 排名 | 攻击方 | 防守方 | 防守方定位 | efficiency | severity |");
  lines.push("|------|--------|--------|-----------|-----------|----------|");
  const top10Counters = counterMatrix.top_n.slice(0, 10);
  top10Counters.forEach((c, i) => {
    lines.push(`| ${i + 1} | ${c.attacker_id} (${c.attacker_commander}) | ${c.defender_id} (${c.defender_commander}) | ${c.defender_role} | ${formatNum(c.efficiency, 4)} | ${c.severity} |`);
  });
  lines.push("");
  lines.push(`阈值：extreme > ${formatNum(counterMatrix.severity_thresholds.extreme, 4)}，strong > ${formatNum(counterMatrix.severity_thresholds.strong, 4)}（基于均值+σ）`);
  lines.push("");

  lines.push("## 6. 补丁建议 Top 10");
  lines.push("");
  lines.push("公式：`suggested_cost = current_cost × clamp(1 / (1 + 0.15 × z), 0.7, 1.3)`");
  lines.push("");
  lines.push("| 排名 | ID | 指挥官 | 种族 | 定位 | 当前造价 | 建议造价 | 比例 | z_internal | 方向 |");
  lines.push("|------|-----|--------|------|------|---------|---------|------|------------|------|");
  const top10Patches = patches.slice(0, 10);
  top10Patches.forEach((p, i) => {
    lines.push(`| ${i + 1} | ${p.id} | ${p.commander} | ${p.race} | ${p.primary_role} | ${formatNum(p.current_cost, 0)} | ${formatNum(p.suggested_cost, 0)} | ${formatNum(p.cost_ratio, 3)} | ${formatNum(p.z_internal, 2)} | ${p.direction} |`);
  });
  lines.push("");

  lines.push("## 7. Caveats（已知限制）");
  lines.push("");
  lines.push("- 公式**不考虑微操收益**（如 Marine 散枪兵），高上限单位会被低估");
  lines.push("- 公式**不模拟资源采集速率**，早期单位与后期单位造价权重相同（不做时间价值折现）");
  lines.push("- 公式**不计算科技树成本**，需要高级科技的单位会被高估");
  lines.push("- 公式**不处理 Behavior 复杂 Buff 链**（如叠加层数动态计算），首版只识别机制标签");
  lines.push("- 公式**不评估指挥官技能/大招**，首版聚焦常驻单位");
  lines.push("- **Skill_value 首版仅基于关键词启发式识别**：仅匹配 Cloak/Heal/Blink/Summon/Stun 等，深度技能评分（含冷却、效果范围、目标数）未实现，故 skill_value 多为 0");
  lines.push("- **Effect 链追踪最多 8 层**：极少数嵌套极深的 Effect 可能解析失败（trace_log 中标注 [depth-limit]）");
  lines.push("- **DisplayAttackCount 处理**：当 effect 链成功追踪到 CEffectDamage 时按 1 处理（实际伤害由 effect 决定）；链失败但武器声明 DisplayAttackCount>1 时按 DisplayAttackCount 近似");
  lines.push("- **TargetFilters 解析**：仅识别 Air/Ground 过滤；详细过滤（如 Psionic/Undead）未使用");
  lines.push("- **克制矩阵为 O(N²)**，对超大规模单位集（>500）可能耗时；本次单位数下可接受");
  lines.push("- **官方基准池说明**：官方合作 mod（starcoop.sc2mod）的 UnitData.xml 含 1743 个 CUnit，但单位 ID 不带指挥官前缀（如 \"Barracks\"、\"Marine\"），无法按指挥官精确归类。本工具将官方 mod 所有有造价的战斗单位（含 Mengsk/Stetmann 独立 mod）合并为基准池，不区分具体指挥官。这符合\"基准锚定\"的统计目标——用 SC2 整体单位分布作为基线，但会引入非指挥官单位（如通用建筑、Beacon）的噪声。");
  lines.push("- **Alenger10 / Alenger11 单位数偏少**（0/2）：这两个 mod 的 UnitData.xml 条目本身较少（11/15），且大部分条目无 LifeMax/CostResource 字段被 shouldSkipUnit 过滤。可能这些 mod 的主战单位定义在共享 mod 中，需后续核查。");
  lines.push("");

  lines.push("## 8. 输出文件清单");
  lines.push("");
  lines.push("- `units-raw.json`：所有单位原始数值（按 commander 分组）");
  lines.push("- `units-scored.json`：含 V_base / S / z 评分");
  lines.push("- `outliers.json`：离群单位清单（|z|>2，按 |z| 降序）");
  lines.push("- `baseline-official.json`：官方基准池分组统计（race × role）的 μ/σ");
  lines.push("- `counter-matrix.json`：每单位最强克制 + Top 10 极端克制");
  lines.push("- `patch-suggestions.json`：补丁建议（仅离群单位）");
  lines.push("- `formula-weights.json`：本次使用的权重（可复现）");
  lines.push("- `report.md`：本报告");
  lines.push("");

  await mkdir(outputDir, { recursive: true });
  await writeFile(join(outputDir, "report.md"), lines.join("\n") + "\n", "utf8");
}

// 辅助：JSON 写入
async function writeJson(path, obj) {
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, JSON.stringify(obj, null, 2) + "\n", "utf8");
}

// 辅助：数字格式化
function formatNum(v, digits = 4) {
  if (v === null || v === undefined || !isFinite(v)) return "0";
  if (Math.abs(v) >= Math.pow(10, digits + 1)) return v.toExponential(2);
  const fixed = Number(v.toFixed(digits));
  return String(fixed);
}
