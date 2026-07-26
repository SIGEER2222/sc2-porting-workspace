// src/compare-report.mjs
// 原版 18 位指挥官 vs 起义 12 位指挥官 对比报告
//
// 输入：
//   official-units-raw.json      原版单位原始指标
//   official-commander-stats.json 原版指挥官强度统计
//   units-scored.json            起义单位评分（含 z_internal / z_official）
//   mod-strength.json            起义指挥官强度评级
//   detailed-units.json          起义单位详情（含形态、回复速率等）
//   formula-weights.json         公式权重
//
// 输出：
//   compare-report.json   结构化对比数据
//   compare-report.md     人类可读对比报告
//
// 对比维度：
//   1. 指挥官层级：avg_S / median_S / avg_cost / avg_ehp / avg_dps / 离群率
//   2. 种族分布：Terr / Zerg / Prot 在两侧的占比
//   3. 角色分布：generalist / splash / anti_air / tank 在两侧的占比
//   4. 单位层级：起义 Top10 强势单位 vs 原版 Top10 强势单位
//   5. 强度差距 (Δ)：起义 avg_S - 原版 avg_S（按种族对齐）
//   6. 综合补丁建议：
//      - 起义偏强 (Δ > 0) 的指挥官 → nerf
//      - 起义偏弱 (Δ < 0) 的指挥官 → buff
//      - 与原版持平的 → 保持

import { readFile, writeFile, mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const balanceRoot = resolve(scriptDir, "..");
const workspaceRoot = resolve(balanceRoot, "..", "..");
const OUTPUT_DIR = resolve(workspaceRoot, "artifacts", "balance", "2026-07-26");

// 指挥官中文名
const COMMANDER_NAMES_ZH = {
  // 原版
  Raynor: "雷诺", Kerrigan: "凯瑞甘", Artanis: "阿塔尼斯", Swann: "斯旺",
  Zagara: "扎加拉", Vorazun: "沃拉尊", Karax: "凯拉克斯", Alarak: "阿拉纳克",
  Nova: "诺娃", Stukov: "斯图科夫", Dehaka: "德哈卡", Fenix: "菲尼克斯",
  Mengsk: "蒙斯克", Stetmann: "斯特曼", Tychus: "泰凯斯", Zeratul: "泽拉图",
  Horner: "霍纳与汉", Abathur: "阿巴瑟",
  // 起义
  Alenger1: "起义 1（人族）", Alenger2: "起义 2（异虫）", Alenger3: "起义 3（人族·蒙斯克风）",
  Alenger4: "起义 4（星灵）", Alenger6: "起义 6（异虫·阿巴瑟风）", Alenger7: "起义 7（人族）",
  Alenger8: "起义 8（星灵）", Alenger9: "起义 9（异虫）", Alenger10: "起义 10（人族）",
  Alenger11: "起义 11（人族）", Alenger12: "起义 12（星灵）", Alenger13: "起义 13（星灵·蒙斯克风）"
};

// 种族中文名
const RACE_ZH = { Terr: "人族", Zerg: "异虫", Prot: "星灵" };

// 角色中文名
const ROLE_ZH = {
  generalist: "通用",
  splash: "溅射",
  anti_air: "对空",
  anti_armored: "反装甲",
  tank: "坦克"
};

function fmt(v, d = 2) {
  if (v === null || v === undefined || !isFinite(v)) return "N/A";
  if (Math.abs(v) >= 1e6) return v.toExponential(2);
  if (Math.abs(v) >= 1e4) return v.toFixed(0);
  return Number(v).toFixed(d);
}

function pct(v, d = 1) {
  if (v === null || v === undefined || !isFinite(v)) return "N/A";
  return (v * 100).toFixed(d) + "%";
}

async function readJson(rel) {
  const p = join(OUTPUT_DIR, rel);
  if (!existsSync(p)) throw new Error(`missing input: ${p}`);
  return JSON.parse(await readFile(p, "utf8"));
}

// 计算单个指挥官的关键指标
function computeCommanderMetrics(units) {
  if (!units || units.length === 0) {
    return {
      unit_count: 0,
      avg_S: 0, median_S: 0, max_S: 0, min_S: 0,
      avg_cost: 0, avg_ehp: 0, avg_dps: 0,
      avg_life: 0, avg_armor: 0, avg_shields: 0,
      avg_range: 0,
      insufficient_sample: true
    };
  }
  const sValues = units.map(u => u.S || u.score || 0).filter(v => isFinite(v) && v > 0).sort((a, b) => a - b);
  const avgS = sValues.length ? sValues.reduce((a, b) => a + b, 0) / sValues.length : 0;
  const medianS = sValues.length ? sValues[Math.floor(sValues.length / 2)] : 0;
  const avgCost = units.reduce((s, u) => s + (u.cost_normalized || 0), 0) / units.length;
  const avgEhp = units.reduce((s, u) => s + (u.ehp || 0), 0) / units.length;
  const avgDps = units.reduce((s, u) => s + (u.dps_general || 0), 0) / units.length;
  const avgLife = units.reduce((s, u) => s + (u.life_max || 0), 0) / units.length;
  const avgArmor = units.reduce((s, u) => s + (u.life_armor || 0), 0) / units.length;
  const avgShields = units.reduce((s, u) => s + (u.shields_max || 0), 0) / units.length;
  const avgRange = units.reduce((s, u) => s + (u.max_range || 0), 0) / units.length;
  return {
    unit_count: units.length,
    avg_S: Number(avgS.toFixed(3)),
    median_S: Number(medianS.toFixed(3)),
    max_S: Number((sValues[sValues.length - 1] || 0).toFixed(3)),
    min_S: Number((sValues[0] || 0).toFixed(3)),
    avg_cost: Number(avgCost.toFixed(1)),
    avg_ehp: Number(avgEhp.toFixed(0)),
    avg_dps: Number(avgDps.toFixed(1)),
    avg_life: Number(avgLife.toFixed(0)),
    avg_armor: Number(avgArmor.toFixed(2)),
    avg_shields: Number(avgShields.toFixed(0)),
    avg_range: Number(avgRange.toFixed(2)),
    insufficient_sample: units.length < 5
  };
}

// 计算种族与角色分布
function computeDistributions(units) {
  const race = {};
  const role = {};
  for (const u of units) {
    const r = u.race || "Unknown";
    race[r] = (race[r] || 0) + 1;
    const ro = u.primary_role || "generalist";
    role[ro] = (role[ro] || 0) + 1;
  }
  const total = units.length || 1;
  const racePct = {};
  for (const [k, v] of Object.entries(race)) racePct[k] = Number((v / total).toFixed(3));
  const rolePct = {};
  for (const [k, v] of Object.entries(role)) rolePct[k] = Number((v / total).toFixed(3));
  return { race: racePct, role: rolePct };
}

async function main() {
  console.log("[compare] 加载数据...");
  const officialRaw = await readJson("official-units-raw.json");
  const officialStats = await readJson("official-commander-stats.json");
  const alengerScored = await readJson("units-scored.json");
  const modStrength = await readJson("mod-strength.json");
  const detailed = await readJson("detailed-units.json");

  // === 1. 原版指挥官指标 ===
  console.log("[compare] 计算原版指挥官指标...");
  const officialCommanders = [];
  for (const [cmdr, data] of Object.entries(officialRaw.commanders)) {
    // 从 official-stats 找到对应统计
    const statsEntry = officialStats.commanders.find(c => c.commander === cmdr);
    // 重新基于 raw 计算指标（更准确）
    const units = data.units || [];
    const scoredUnits = units.map(u => ({
      ...u,
      S: u.cost_normalized > 0 ? (u.ehp * (u.dps_general || 0) + (u.skill_value || 0)) / u.cost_normalized : 0
    }));
    const metrics = computeCommanderMetrics(scoredUnits);
    const dist = computeDistributions(scoredUnits);
    officialCommanders.push({
      commander: cmdr,
      commander_zh: COMMANDER_NAMES_ZH[cmdr] || cmdr,
      ...metrics,
      race_distribution: dist.race,
      role_distribution: dist.role,
      outlier_rate: statsEntry ? statsEntry.outlier_rate : 0
    });
  }
  // 按 avg_S 降序
  officialCommanders.sort((a, b) => {
    if (a.insufficient_sample !== b.insufficient_sample) return a.insufficient_sample ? 1 : -1;
    return b.avg_S - a.avg_S;
  });

  // === 2. 起义指挥官指标 ===
  console.log("[compare] 计算起义指挥官指标...");
  // alengerScored.units 是评分后的扁平单位列表
  const alengerUnitsByCmdr = {};
  for (const u of alengerScored.units) {
    if (!alengerUnitsByCmdr[u.commander]) alengerUnitsByCmdr[u.commander] = [];
    alengerUnitsByCmdr[u.commander].push(u);
  }

  // strength map 用于读取 grade / final_score / outlier_rate
  const strengthMap = new Map();
  for (const r of modStrength.ranking) strengthMap.set(r.commander, r);

  const alengerCommanders = [];
  for (const [cmdr, units] of Object.entries(alengerUnitsByCmdr)) {
    const scoredUnits = units.map(u => ({
      ...u,
      S: u.S || 0,
      cost_normalized: u.cost_normalized || 0,
      ehp: u.ehp || 0,
      dps_general: u.dps_general || 0,
      life_max: u.life_max || 0,
      life_armor: u.life_armor || 0,
      shields_max: u.shields_max || 0,
      max_range: u.max_range || 0,
      race: u.race || "Unknown",
      primary_role: u.primary_role || "generalist"
    }));
    const metrics = computeCommanderMetrics(scoredUnits);
    const dist = computeDistributions(scoredUnits);
    const s = strengthMap.get(cmdr) || {};
    alengerCommanders.push({
      commander: cmdr,
      commander_zh: COMMANDER_NAMES_ZH[cmdr] || cmdr,
      ...metrics,
      race_distribution: dist.race,
      role_distribution: dist.role,
      grade: s.grade || "N/A",
      final_score: s.final_score || 0,
      outlier_rate: s.outlier_rate || 0,
      delta_vs_official: s.delta_vs_official || 0
    });
  }
  // 按编号排序
  alengerCommanders.sort((a, b) => {
    const na = parseInt(a.commander.replace("Alenger", ""), 10);
    const nb = parseInt(b.commander.replace("Alenger", ""), 10);
    return na - nb;
  });

  // === 3. 整体对比 ===
  console.log("[compare] 计算整体对比...");
  const officialAllUnits = [];
  for (const data of Object.values(officialRaw.commanders)) {
    for (const u of data.units) {
      officialAllUnits.push({
        ...u,
        S: u.cost_normalized > 0 ? (u.ehp * (u.dps_general || 0) + (u.skill_value || 0)) / u.cost_normalized : 0
      });
    }
  }
  const alengerAllUnits = alengerScored.units.map(u => ({ ...u, S: u.S || 0 }));

  const officialOverall = computeCommanderMetrics(officialAllUnits);
  const alengerOverall = computeCommanderMetrics(alengerAllUnits);
  const officialDist = computeDistributions(officialAllUnits);
  const alengerDist = computeDistributions(alengerAllUnits);

  // Δ_global：起义均值 - 原版均值
  const delta = {
    avg_S: alengerOverall.avg_S - officialOverall.avg_S,
    median_S: alengerOverall.median_S - officialOverall.median_S,
    avg_cost: alengerOverall.avg_cost - officialOverall.avg_cost,
    avg_ehp: alengerOverall.avg_ehp - officialOverall.avg_ehp,
    avg_dps: alengerOverall.avg_dps - officialOverall.avg_dps,
    avg_life: alengerOverall.avg_life - officialOverall.avg_life,
    avg_armor: alengerOverall.avg_armor - officialOverall.avg_armor,
    avg_shields: alengerOverall.avg_shields - officialOverall.avg_shields,
    avg_range: alengerOverall.avg_range - officialOverall.avg_range
  };

  // Δ 比率 (起义 / 原版)
  const ratio = {};
  for (const k of Object.keys(delta)) {
    const o = officialOverall[k] || 0;
    ratio[k] = o > 0 ? Number(((alengerOverall[k] / o)).toFixed(3)) : 0;
  }

  // === 4. 按种族分组对比 ===
  console.log("[compare] 按种族分组对比...");
  const byRace = {};
  for (const race of ["Terr", "Zerg", "Prot"]) {
    const officialRace = officialAllUnits.filter(u => u.race === race);
    const alengerRace = alengerAllUnits.filter(u => u.race === race);
    byRace[race] = {
      race_zh: RACE_ZH[race],
      official: {
        unit_count: officialRace.length,
        ...computeCommanderMetrics(officialRace)
      },
      alenger: {
        unit_count: alengerRace.length,
        ...computeCommanderMetrics(alengerRace)
      },
      delta_avg_S: computeCommanderMetrics(alengerRace).avg_S - computeCommanderMetrics(officialRace).avg_S
    };
  }

  // === 5. Top 强势单位对比 ===
  console.log("[compare] 计算 Top 强势单位...");
  const officialTopUnits = [...officialAllUnits]
    .filter(u => u.S > 0)
    .sort((a, b) => b.S - a.S)
    .slice(0, 15)
    .map(u => ({
      id: u.id,
      commander: u.commander || "Unknown",
      race: u.race,
      S: Number(u.S.toFixed(3)),
      cost_normalized: u.cost_normalized,
      dps_general: u.dps_general,
      ehp: u.ehp,
      life_max: u.life_max
    }));

  const alengerTopUnits = [...alengerAllUnits]
    .filter(u => u.S > 0)
    .sort((a, b) => b.S - a.S)
    .slice(0, 15)
    .map(u => ({
      id: u.id,
      commander: u.commander,
      race: u.race,
      S: Number((u.S || 0).toFixed(3)),
      cost_normalized: u.cost_normalized,
      dps_general: u.dps_general,
      ehp: u.ehp,
      life_max: u.life_max,
      primary_role: u.primary_role
    }));

  // === 6. 综合补丁建议 ===
  console.log("[compare] 生成补丁建议...");
  // 计算原版 avg_S 基线（仅取样本充足的原版指挥官）
  const officialBaselineCommanders = officialCommanders.filter(c => !c.insufficient_sample);
  const officialBaselineAvgS = officialBaselineCommanders.length > 0
    ? officialBaselineCommanders.reduce((s, c) => s + c.avg_S, 0) / officialBaselineCommanders.length
    : 0;
  const officialBaselineMedianS = (() => {
    const arr = officialBaselineCommanders.map(c => c.avg_S).sort((a, b) => a - b);
    return arr.length ? arr[Math.floor(arr.length / 2)] : 0;
  })();

  // 为每个起义指挥官生成对比补丁建议
  const patchSuggestions = [];
  for (const a of alengerCommanders) {
    if (a.insufficient_sample) continue;

    // 找到种族相同的原版指挥官作为参照
    const sameRaceOfficial = officialCommanders.filter(c =>
      !c.insufficient_sample && c.race_distribution && c.race_distribution[Object.keys(a.race_distribution)[0]] === 1
    );
    let referenceAvgS;
    let referenceType;
    if (sameRaceOfficial.length > 0) {
      referenceAvgS = sameRaceOfficial.reduce((s, c) => s + c.avg_S, 0) / sameRaceOfficial.length;
      referenceType = `同种族原版均值 (${sameRaceOfficial.map(c => c.commander_zh).join(", ")})`;
    } else {
      referenceAvgS = officialBaselineAvgS;
      referenceType = "原版整体均值";
    }

    const deltaS = a.avg_S - referenceAvgS;
    const deltaRatio = referenceAvgS > 0 ? a.avg_S / referenceAvgS : 1;

    // 建议方向
    let direction;
    let costAdjust;
    let reason;
    if (deltaRatio > 1.5) {
      direction = "nerf";
      costAdjust = 1.20;
      reason = `avg_S=${fmt(a.avg_S)} 远高于${referenceType}=${fmt(referenceAvgS)}（Δ=+${fmt(deltaS)}, 比率 ${fmt(deltaRatio)}×），强烈 nerf`;
    } else if (deltaRatio > 1.2) {
      direction = "nerf";
      costAdjust = 1.10;
      reason = `avg_S=${fmt(a.avg_S)} 高于${referenceType}=${fmt(referenceAvgS)}（Δ=+${fmt(deltaS)}, 比率 ${fmt(deltaRatio)}×），轻度 nerf`;
    } else if (deltaRatio < 0.7) {
      direction = "buff";
      costAdjust = 0.85;
      reason = `avg_S=${fmt(a.avg_S)} 远低于${referenceType}=${fmt(referenceAvgS)}（Δ=${fmt(deltaS)}, 比率 ${fmt(deltaRatio)}×），强烈 buff`;
    } else if (deltaRatio < 0.85) {
      direction = "buff";
      costAdjust = 0.92;
      reason = `avg_S=${fmt(a.avg_S)} 低于${referenceType}=${fmt(referenceAvgS)}（Δ=${fmt(deltaS)}, 比率 ${fmt(deltaRatio)}×），轻度 buff`;
    } else {
      direction = "保持";
      costAdjust = 1.0;
      reason = `avg_S=${fmt(a.avg_S)} 与${referenceType}=${fmt(referenceAvgS)} 接近（Δ=${fmt(deltaS)}, 比率 ${fmt(deltaRatio)}×），无需调整`;
    }

    patchSuggestions.push({
      commander: a.commander,
      commander_zh: a.commander_zh,
      grade: a.grade,
      avg_S: a.avg_S,
      reference_avg_S: Number(referenceAvgS.toFixed(3)),
      reference_type: referenceType,
      delta_S: Number(deltaS.toFixed(3)),
      delta_ratio: Number(deltaRatio.toFixed(3)),
      direction,
      cost_adjust: costAdjust,
      reason,
      // 同时考虑离群率
      outlier_rate: a.outlier_rate,
      // 综合建议：结合离群率与对比
      combined_adjust: (() => {
        let mult = costAdjust;
        if (a.outlier_rate > 0.25 && direction === "nerf") {
          mult *= 1.05;
        } else if (a.outlier_rate < 0.05 && direction === "buff") {
          mult *= 0.95;
        }
        return Number(mult.toFixed(3));
      })()
    });
  }

  // === 7. 写 JSON ===
  console.log("[compare] 写入 compare-report.json...");
  await mkdir(OUTPUT_DIR, { recursive: true });
  await writeFile(
    join(OUTPUT_DIR, "compare-report.json"),
    JSON.stringify({
      schema_version: 1,
      generated_at: new Date().toISOString(),
      summary: {
        official_commander_count: officialCommanders.filter(c => !c.insufficient_sample).length,
        official_commander_total: officialCommanders.length,
        official_unit_count: officialAllUnits.length,
        alenger_commander_count: alengerCommanders.filter(c => !c.insufficient_sample).length,
        alenger_commander_total: alengerCommanders.length,
        alenger_unit_count: alengerAllUnits.length,
        official_baseline_avg_S: Number(officialBaselineAvgS.toFixed(3)),
        official_baseline_median_S: Number(officialBaselineMedianS.toFixed(3)),
        alenger_avg_S: alengerOverall.avg_S,
        delta_global: Number(delta.avg_S.toFixed(3)),
        ratio_global: ratio.avg_S
      },
      overall: {
        official: officialOverall,
        alenger: alengerOverall,
        delta,
        ratio
      },
      race_distribution: {
        official: officialDist.race,
        alenger: alengerDist.race
      },
      role_distribution: {
        official: officialDist.role,
        alenger: alengerDist.role
      },
      by_race: byRace,
      official_commanders: officialCommanders,
      alenger_commanders: alengerCommanders,
      top_units: {
        official_top_15: officialTopUnits,
        alenger_top_15: alengerTopUnits
      },
      patch_suggestions: patchSuggestions
    }, null, 2),
    "utf8"
  );

  // === 8. 写 Markdown 报告 ===
  console.log("[compare] 写入 compare-report.md...");
  const md = [];
  md.push("# SC2 原版 vs 起义指挥官 对比报告");
  md.push("");
  md.push(`**生成时间**：${new Date().toISOString()}`);
  md.push(`**对比维度**：avg_S / median_S / avg_cost / avg_ehp / avg_dps / 种族分布 / 角色分布`);
  md.push(`**原版样本**：${officialCommanders.filter(c => !c.insufficient_sample).length} 位指挥官 / ${officialAllUnits.length} 个单位（共 ${officialCommanders.length} 位指挥官，其中 ${officialCommanders.filter(c => c.insufficient_sample).length} 位样本不足）`);
  md.push(`**起义样本**：${alengerCommanders.filter(c => !c.insufficient_sample).length} 位指挥官 / ${alengerAllUnits.length} 个单位`);
  md.push("");
  md.push("---");
  md.push("");

  // === 0. 总览 ===
  md.push("## 0. 全局总览");
  md.push("");
  md.push("| 指标 | 原版 | 起义 | Δ（起义-原版） | 比率（起义/原版） |");
  md.push("|------|------|------|----------------|---------------------|");
  md.push(`| 单位数 | ${officialOverall.unit_count} | ${alengerOverall.unit_count} | ${alengerOverall.unit_count - officialOverall.unit_count} | ${(alengerOverall.unit_count / officialOverall.unit_count).toFixed(2)}× |`);
  md.push(`| 平均 S 值 | ${fmt(officialOverall.avg_S)} | ${fmt(alengerOverall.avg_S)} | ${fmt(delta.avg_S)} | ${ratio.avg_S}× |`);
  md.push(`| 中位 S 值 | ${fmt(officialOverall.median_S)} | ${fmt(alengerOverall.median_S)} | ${fmt(delta.median_S)} | ${ratio.median_S}× |`);
  md.push(`| 平均造价 | ${fmt(officialOverall.avg_cost)} | ${fmt(alengerOverall.avg_cost)} | ${fmt(delta.avg_cost)} | ${ratio.avg_cost}× |`);
  md.push(`| 平均 EHP | ${fmt(officialOverall.avg_ehp)} | ${fmt(alengerOverall.avg_ehp)} | ${fmt(delta.avg_ehp)} | ${ratio.avg_ehp}× |`);
  md.push(`| 平均 DPS | ${fmt(officialOverall.avg_dps)} | ${fmt(alengerOverall.avg_dps)} | ${fmt(delta.avg_dps)} | ${ratio.avg_dps}× |`);
  md.push(`| 平均血量 | ${fmt(officialOverall.avg_life)} | ${fmt(alengerOverall.avg_life)} | ${fmt(delta.avg_life)} | ${ratio.avg_life}× |`);
  md.push(`| 平均护甲 | ${fmt(officialOverall.avg_armor)} | ${fmt(alengerOverall.avg_armor)} | ${fmt(delta.avg_armor)} | ${ratio.avg_armor}× |`);
  md.push(`| 平均护盾 | ${fmt(officialOverall.avg_shields)} | ${fmt(alengerOverall.avg_shields)} | ${fmt(delta.avg_shields)} | ${ratio.avg_shields}× |`);
  md.push(`| 平均射程 | ${fmt(officialOverall.avg_range)} | ${fmt(alengerOverall.avg_range)} | ${fmt(delta.avg_range)} | ${ratio.avg_range}× |`);
  md.push("");
  md.push(`**关键结论**：起义平均 S 值为原版的 **${ratio.avg_S}×**（Δ=${fmt(delta.avg_S)}），整体强度${ratio.avg_S > 1.2 ? "**显著偏高**" : ratio.avg_S > 1.05 ? "略偏高" : ratio.avg_S < 0.85 ? "**显著偏低**" : ratio.avg_S < 0.95 ? "略偏低" : "基本持平"}。`);
  md.push("");

  // === 1. 种族与角色分布 ===
  md.push("## 1. 种族与角色分布对比");
  md.push("");
  md.push("### 1.1 种族分布");
  md.push("");
  md.push("| 种族 | 原版占比 | 起义占比 |");
  md.push("|------|----------|----------|");
  for (const race of ["Terr", "Zerg", "Prot"]) {
    md.push(`| ${RACE_ZH[race]} (${race}) | ${pct(officialDist.race[race] || 0)} | ${pct(alengerDist.race[race] || 0)} |`);
  }
  md.push("");

  md.push("### 1.2 角色分布");
  md.push("");
  md.push("| 角色 | 原版占比 | 起义占比 |");
  md.push("|------|----------|----------|");
  const allRoles = new Set([...Object.keys(officialDist.role), ...Object.keys(alengerDist.role)]);
  for (const role of allRoles) {
    md.push(`| ${ROLE_ZH[role] || role} | ${pct(officialDist.role[role] || 0)} | ${pct(alengerDist.role[role] || 0)} |`);
  }
  md.push("");

  // === 2. 按种族分组对比 ===
  md.push("## 2. 按种族分组对比");
  md.push("");
  for (const race of ["Terr", "Zerg", "Prot"]) {
    const r = byRace[race];
    md.push(`### 2.${race === "Terr" ? "1" : race === "Zerg" ? "2" : "3"} ${RACE_ZH[race]}（${race}）`);
    md.push("");
    md.push("| 指标 | 原版 | 起义 | Δ |");
    md.push("|------|------|------|---|");
    md.push(`| 单位数 | ${r.official.unit_count} | ${r.alenger.unit_count} | ${r.alenger.unit_count - r.official.unit_count} |`);
    md.push(`| 平均 S 值 | ${fmt(r.official.avg_S)} | ${fmt(r.alenger.avg_S)} | ${fmt(r.delta_avg_S)} |`);
    md.push(`| 平均造价 | ${fmt(r.official.avg_cost)} | ${fmt(r.alenger.avg_cost)} | ${fmt(r.alenger.avg_cost - r.official.avg_cost)} |`);
    md.push(`| 平均 EHP | ${fmt(r.official.avg_ehp)} | ${fmt(r.alenger.avg_ehp)} | ${fmt(r.alenger.avg_ehp - r.official.avg_ehp)} |`);
    md.push(`| 平均 DPS | ${fmt(r.official.avg_dps)} | ${fmt(r.alenger.avg_dps)} | ${fmt(r.alenger.avg_dps - r.official.avg_dps)} |`);
    md.push("");
  }

  // === 3. 原版指挥官强度排名 ===
  md.push("## 3. 原版 18 位指挥官强度排名");
  md.push("");
  md.push("> 样本不足（单位数 < 5）的指挥官用 *N/A* 标记，仅作参考。");
  md.push("");
  md.push("| 排名 | 指挥官 | 单位数 | avg_S | median_S | max_S | 离群率 | avg_cost | avg_ehp | avg_dps |");
  md.push("|------|--------|--------|-------|----------|-------|--------|----------|---------|---------|");
  officialCommanders.forEach((c, i) => {
    const mark = c.insufficient_sample ? " (N/A)" : "";
    md.push(`| ${i + 1} | ${c.commander_zh} (${c.commander})${mark} | ${c.unit_count} | ${fmt(c.avg_S)} | ${fmt(c.median_S)} | ${fmt(c.max_S)} | ${pct(c.outlier_rate)} | ${fmt(c.avg_cost)} | ${fmt(c.avg_ehp)} | ${fmt(c.avg_dps)} |`);
  });
  md.push("");
  md.push(`**原版基线 avg_S 均值**（仅样本充足指挥官）：**${fmt(officialBaselineAvgS)}**`);
  md.push(`**原版基线 avg_S 中位数**（仅样本充足指挥官）：**${fmt(officialBaselineMedianS)}**`);
  md.push("");

  // === 4. 起义指挥官强度排名 ===
  md.push("## 4. 起义 12 位指挥官强度排名");
  md.push("");
  md.push("| 排名 | 指挥官 | 等级 | 单位数 | avg_S | median_S | max_S | 离群率 | avg_cost | avg_ehp | avg_dps | Δ vs 官方 |");
  md.push("|------|--------|------|--------|-------|----------|-------|--------|----------|---------|---------|-----------|");
  const alengerSorted = [...alengerCommanders].sort((a, b) => b.avg_S - a.avg_S);
  alengerSorted.forEach((c, i) => {
    const mark = c.insufficient_sample ? " (N/A)" : "";
    md.push(`| ${i + 1} | ${c.commander_zh} (${c.commander})${mark} | ${c.grade} | ${c.unit_count} | ${fmt(c.avg_S)} | ${fmt(c.median_S)} | ${fmt(c.max_S)} | ${pct(c.outlier_rate)} | ${fmt(c.avg_cost)} | ${fmt(c.avg_ehp)} | ${fmt(c.avg_dps)} | ${fmt(c.delta_vs_official)} |`);
  });
  md.push("");

  // === 5. Top 强势单位对比 ===
  md.push("## 5. Top 15 强势单位对比");
  md.push("");
  md.push("### 5.1 原版 Top 15（按 S 值降序）");
  md.push("");
  md.push("| 排名 | 单位 ID | 指挥官 | 种族 | S 值 | 造价 | DPS | EHP | 血量 |");
  md.push("|------|---------|--------|------|------|------|-----|-----|------|");
  officialTopUnits.forEach((u, i) => {
    md.push(`| ${i + 1} | ${u.id} | ${u.commander} | ${RACE_ZH[u.race] || u.race} | ${fmt(u.S)} | ${fmt(u.cost_normalized)} | ${fmt(u.dps_general)} | ${fmt(u.ehp)} | ${fmt(u.life_max)} |`);
  });
  md.push("");

  md.push("### 5.2 起义 Top 15（按 S 值降序）");
  md.push("");
  md.push("| 排名 | 单位 ID | 指挥官 | 种族 | S 值 | 造价 | DPS | EHP | 血量 | 角色 |");
  md.push("|------|---------|--------|------|------|------|-----|-----|------|------|");
  alengerTopUnits.forEach((u, i) => {
    md.push(`| ${i + 1} | ${u.id} | ${u.commander} | ${RACE_ZH[u.race] || u.race} | ${fmt(u.S)} | ${fmt(u.cost_normalized)} | ${fmt(u.dps_general)} | ${fmt(u.ehp)} | ${fmt(u.life_max)} | ${ROLE_ZH[u.primary_role] || u.primary_role} |`);
  });
  md.push("");

  // === 6. 综合补丁建议 ===
  md.push("## 6. 综合补丁建议（基于原版对比）");
  md.push("");
  md.push("> 调整方向：起义 avg_S 与**同种族原版指挥官 avg_S 均值**对比，超过 1.2× 建议 nerf，低于 0.85× 建议 buff。");
  md.push("> 综合系数：direction × cost_adjust × 离群率修正（nerf 且离群率 > 25% 时 ×1.05，buff 且离群率 < 5% 时 ×0.95）。");
  md.push("");
  md.push("| 指挥官 | 等级 | avg_S | 参照值 | 参照类型 | Δ S | 比率 | 方向 | 基础系数 | 综合系数 | 离群率 | 理由 |");
  md.push("|--------|------|-------|--------|----------|-----|------|------|----------|----------|--------|------|");
  for (const p of patchSuggestions) {
    md.push(`| ${p.commander_zh} | ${p.grade} | ${fmt(p.avg_S)} | ${fmt(p.reference_avg_S)} | ${p.reference_type} | ${fmt(p.delta_S)} | ${p.delta_ratio}× | ${p.direction} | ${p.cost_adjust}× | ${p.combined_adjust}× | ${pct(p.outlier_rate)} | ${p.reason} |`);
  }
  md.push("");

  // === 7. 关键发现 ===
  md.push("## 7. 关键发现与建议");
  md.push("");
  md.push("### 7.1 整体偏差");
  md.push("");
  md.push(`- **avg_S 比率**：起义整体平均 S 值为原版的 **${ratio.avg_S}×**`);
  md.push(`- **avg_cost 比率**：起义平均造价为原版的 **${ratio.avg_cost}×**`);
  md.push(`- **avg_ehp 比率**：起义平均 EHP 为原版的 **${ratio.avg_ehp}×**`);
  md.push(`- **avg_dps 比率**：起义平均 DPS 为原版的 **${ratio.avg_dps}×**`);
  md.push("");
  if (ratio.avg_S > 1.5) {
    md.push(`**结论**：起义指挥官整体强度**严重超标**（S 值 ${ratio.avg_S}×），建议大规模 nerf。`);
  } else if (ratio.avg_S > 1.2) {
    md.push(`**结论**：起义指挥官整体强度**明显偏高**（S 值 ${ratio.avg_S}×），建议对偏强指挥官进行 nerf。`);
  } else if (ratio.avg_S < 0.7) {
    md.push(`**结论**：起义指挥官整体强度**严重不足**（S 值 ${ratio.avg_S}×），建议大规模 buff。`);
  } else if (ratio.avg_S < 0.85) {
    md.push(`**结论**：起义指挥官整体强度**偏低**（S 值 ${ratio.avg_S}×），建议对偏弱指挥官进行 buff。`);
  } else {
    md.push(`**结论**：起义指挥官整体强度与原版**基本持平**（S 值 ${ratio.avg_S}×），仅需对个别偏移指挥官进行调整。`);
  }
  md.push("");

  md.push("### 7.2 偏强指挥官（建议 nerf）");
  md.push("");
  const nerfList = patchSuggestions.filter(p => p.direction === "nerf").sort((a, b) => b.delta_ratio - a.delta_ratio);
  if (nerfList.length === 0) {
    md.push("- 无");
  } else {
    for (const p of nerfList) {
      md.push(`- **${p.commander_zh}**：avg_S=${fmt(p.avg_S)}，参照 ${p.reference_type}=${fmt(p.reference_avg_S)}（${p.delta_ratio}×），综合系数 ×${p.combined_adjust}`);
    }
  }
  md.push("");

  md.push("### 7.3 偏弱指挥官（建议 buff）");
  md.push("");
  const buffList = patchSuggestions.filter(p => p.direction === "buff").sort((a, b) => a.delta_ratio - b.delta_ratio);
  if (buffList.length === 0) {
    md.push("- 无");
  } else {
    for (const p of buffList) {
      md.push(`- **${p.commander_zh}**：avg_S=${fmt(p.avg_S)}，参照 ${p.reference_type}=${fmt(p.reference_avg_S)}（${p.delta_ratio}×），综合系数 ×${p.combined_adjust}`);
    }
  }
  md.push("");

  md.push("### 7.4 与原版持平的指挥官");
  md.push("");
  const keepList = patchSuggestions.filter(p => p.direction === "保持");
  if (keepList.length === 0) {
    md.push("- 无");
  } else {
    for (const p of keepList) {
      md.push(`- **${p.commander_zh}**：avg_S=${fmt(p.avg_S)}，参照 ${p.reference_type}=${fmt(p.reference_avg_S)}（${p.delta_ratio}×），无需调整`);
    }
  }
  md.push("");

  // === 8. 应用建议 ===
  md.push("## 8. 应用建议");
  md.push("");
  md.push("### 8.1 与现有 balance-plan 的关系");
  md.push("");
  md.push("- **balance-plan.md**：基于起义单位**内部离群值**（z_internal）+ 持续回盾 + 满生物质 + 战甲人格 + 指挥官整体强度的细粒度调整");
  md.push("- **compare-report.md（本报告）**：基于**原版对比**（avg_S vs 同种族原版均值）的指挥官级整体调整");
  md.push("");
  md.push("### 8.2 推荐应用顺序");
  md.push("");
  md.push("1. **第一层**：先按 compare-report 的指挥官级综合系数调整整体造价");
  md.push("2. **第二层**：再按 balance-plan 的单位级细粒度调整处理个别离群单位");
  md.push("3. **校验**：调整后重新计算 avg_S，确认起义指挥官强度收敛到原版 0.85× ~ 1.15× 范围内");
  md.push("");
  md.push("### 8.3 注意事项");
  md.push("");
  md.push("- 原版部分指挥官（凯瑞甘/斯旺/沃拉尊/菲尼克斯/蒙斯克/泰凯斯/泽拉图/霍纳与汉）因 mod 数据未完整加载，单位数为 0，未纳入对比基线");
  md.push("- 起义指挥官中 Alenger5 / Alenger14 不存在，Alenger10 / Alenger11 单位样本不足，已跳过");
  md.push("- 综合系数仅作为整体调整方向参考，具体单位仍需结合 balance-plan.md 的细粒度建议");
  md.push("");

  await writeFile(join(OUTPUT_DIR, "compare-report.md"), md.join("\n"), "utf8");

  console.log("[compare] === 完成 ===");
  console.log(`[compare] 输出目录: ${OUTPUT_DIR}`);
  console.log(`[compare] 原版指挥官: ${officialCommanders.filter(c => !c.insufficient_sample).length} 有效 / ${officialCommanders.length} 总计`);
  console.log(`[compare] 起义指挥官: ${alengerCommanders.filter(c => !c.insufficient_sample).length} 有效 / ${alengerCommanders.length} 总计`);
  console.log(`[compare] 原版单位数: ${officialAllUnits.length}`);
  console.log(`[compare] 起义单位数: ${alengerAllUnits.length}`);
  console.log(`[compare] 全局 Δ avg_S: ${fmt(delta.avg_S)} (比率 ${ratio.avg_S}×)`);
  console.log(`[compare] nerf 建议: ${nerfList.length} 位指挥官`);
  console.log(`[compare] buff 建议: ${buffList.length} 位指挥官`);
  console.log(`[compare] 保持建议: ${keepList.length} 位指挥官`);
}

main().catch(err => {
  console.error("[compare] FATAL:", err);
  console.error(err.stack);
  process.exit(1);
});
