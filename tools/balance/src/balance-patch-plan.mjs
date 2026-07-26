// src/balance-patch-plan.mjs
// 基于原版 18 位指挥官基线生成完整的平衡补丁方案
//
// 输入：
//   official-units-raw.json      原版单位原始指标
//   official-commander-stats.json 原版指挥官强度统计
//   units-scored.json            起义单位评分
//   mod-strength.json            起义指挥官强度评级
//   mengsk-vs-alenger3.json      蒙斯克 vs 起义3 专项对比
//   detailed-units.json          起义单位详情
//
// 输出：
//   balance-patch-plan.json  结构化补丁方案
//   balance-patch-plan.md    人类可读补丁方案
//
// 补丁方案三层结构：
//   1. 整体层：起义指挥官整体 nerf 系数（基于同种族原版均值对比）
//   2. 指挥官层：每位起义指挥官的具体调整（综合系数 = 基础系数 × 离群率修正）
//   3. 单位层：基于 Mengsk vs Alenger3 专项对比的细粒度单位级 nerf

import { readFile, writeFile, mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const balanceRoot = resolve(scriptDir, "..");
const workspaceRoot = resolve(balanceRoot, "..", "..");
const OUTPUT_DIR = resolve(workspaceRoot, "artifacts", "balance", "2026-07-26");

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

const RACE_ZH = { Terr: "人族", Zerg: "异虫", Prot: "星灵" };

function fmt(v, d = 2) {
  if (v === null || v === undefined || !isFinite(v)) return "N/A";
  if (Math.abs(v) >= 1e6) return v.toExponential(2);
  if (Math.abs(v) >= 1e4) return v.toFixed(0);
  return Number(v).toFixed(d);
}

async function readJson(rel) {
  const p = join(OUTPUT_DIR, rel);
  if (!existsSync(p)) throw new Error(`missing input: ${p}`);
  return JSON.parse(await readFile(p, "utf8"));
}

// 计算单个指挥官的指标
function computeMetrics(units) {
  if (!units || units.length === 0) {
    return { unit_count: 0, avg_S: 0, median_S: 0, max_S: 0, min_S: 0, insufficient_sample: true };
  }
  const sValues = units.map(u => u.S || 0).filter(v => isFinite(v) && v > 0).sort((a, b) => a - b);
  const avgS = sValues.length ? sValues.reduce((a, b) => a + b, 0) / sValues.length : 0;
  const medianS = sValues.length ? sValues[Math.floor(sValues.length / 2)] : 0;
  return {
    unit_count: units.length,
    avg_S: Number(avgS.toFixed(3)),
    median_S: Number(medianS.toFixed(3)),
    max_S: Number((sValues[sValues.length - 1] || 0).toFixed(3)),
    min_S: Number((sValues[0] || 0).toFixed(3)),
    insufficient_sample: units.length < 5
  };
}

async function main() {
  console.log("[patch] === 生成平衡补丁方案 ===");
  const officialRaw = await readJson("official-units-raw.json");
  const officialStats = await readJson("official-commander-stats.json");
  const alengerScored = await readJson("units-scored.json");
  const modStrength = await readJson("mod-strength.json");
  const mengskVsAlenger3 = await readJson("mengsk-vs-alenger3.json");

  // === 1. 计算原版 18 位指挥官基线 ===
  console.log("[patch] 计算原版基线...");
  const officialCommanders = [];
  for (const [cmdr, data] of Object.entries(officialRaw.commanders)) {
    const units = data.units || [];
    const scoredUnits = units.map(u => ({
      ...u,
      S: u.cost_normalized > 0 ? (u.ehp * (u.dps_general || 0) + (u.skill_value || 0)) / u.cost_normalized : 0
    }));
    const metrics = computeMetrics(scoredUnits);
    const statsEntry = officialStats.commanders.find(c => c.commander === cmdr);
    officialCommanders.push({
      commander: cmdr,
      commander_zh: COMMANDER_NAMES_ZH[cmdr] || cmdr,
      race: data.race || (cmdr === "Mengsk" || cmdr === "Raynor" || cmdr === "Swann" || cmdr === "Nova" || cmdr === "Stetmann" || cmdr === "Tychus" || cmdr === "Horner" ? "Terr" : (cmdr === "Kerrigan" || cmdr === "Zagara" || cmdr === "Stukov" || cmdr === "Dehaka" || cmdr === "Abathur" ? "Zerg" : "Prot")),
      ...metrics,
      outlier_rate: statsEntry ? statsEntry.outlier_rate : 0
    });
  }

  // 按种族分组计算原版基线
  const officialByRace = {};
  for (const race of ["Terr", "Zerg", "Prot"]) {
    const raceCommanders = officialCommanders.filter(c => c.race === race && !c.insufficient_sample);
    const allUnitsOfRace = [];
    for (const [cmdr, data] of Object.entries(officialRaw.commanders)) {
      const cmdrEntry = officialCommanders.find(c => c.commander === cmdr);
      if (cmdrEntry && cmdrEntry.race === race) {
        for (const u of data.units) {
          allUnitsOfRace.push({
            ...u,
            S: u.cost_normalized > 0 ? (u.ehp * (u.dps_general || 0) + (u.skill_value || 0)) / u.cost_normalized : 0
          });
        }
      }
    }
    const raceMetrics = computeMetrics(allUnitsOfRace);
    officialByRace[race] = {
      race_zh: RACE_ZH[race],
      commander_count_sample: raceCommanders.length,
      commander_count_total: officialCommanders.filter(c => c.race === race).length,
      commanders_sample: raceCommanders.map(c => c.commander_zh),
      commanders_excluded: officialCommanders.filter(c => c.race === race && c.insufficient_sample).map(c => c.commander_zh),
      ...raceMetrics
    };
  }

  // 原版整体基线（仅样本充足指挥官）
  const officialSampleCommanders = officialCommanders.filter(c => !c.insufficient_sample);
  const officialSampleAvgS = officialSampleCommanders.reduce((s, c) => s + c.avg_S, 0) / officialSampleCommanders.length;
  const officialBaseline = {
    commander_count_total: officialCommanders.length,
    commander_count_sample: officialSampleCommanders.length,
    commander_count_excluded: officialCommanders.length - officialSampleCommanders.length,
    avg_S_sample: Number(officialSampleAvgS.toFixed(3)),
    by_race: officialByRace,
    overall_avg_S: Number(officialSampleAvgS.toFixed(3))
  };

  // === 2. 计算起义指挥官的调整方案 ===
  console.log("[patch] 计算起义指挥官调整方案...");
  const alengerUnitsByCmdr = {};
  for (const u of alengerScored.units) {
    if (!alengerUnitsByCmdr[u.commander]) alengerUnitsByCmdr[u.commander] = [];
    alengerUnitsByCmdr[u.commander].push(u);
  }
  const strengthMap = new Map();
  for (const r of modStrength.ranking) strengthMap.set(r.commander, r);

  const patchPlan = [];
  for (const [cmdr, units] of Object.entries(alengerUnitsByCmdr)) {
    const scoredUnits = units.map(u => ({ ...u, S: u.S || 0 }));
    const metrics = computeMetrics(scoredUnits);
    if (metrics.insufficient_sample) {
      // 跳过样本不足的起义指挥官
      continue;
    }
    const s = strengthMap.get(cmdr) || {};
    // 从 race_distribution 取主导 race（更准确）
    let race = "Unknown";
    if (s.race_distribution) {
      let maxCount = 0;
      for (const [r, c] of Object.entries(s.race_distribution)) {
        if (c > maxCount) { maxCount = c; race = r; }
      }
    }
    if (race === "Unknown") race = units[0]?.race || "Unknown";

    // 参照值选择：
    // 优先同种族原版均值（样本充足指挥官 > 1 位时）
    // 否则用原版整体均值
    const sameRaceBaseline = officialByRace[race];
    let reference, referenceType;
    if (sameRaceBaseline && sameRaceBaseline.commander_count_sample >= 2) {
      reference = sameRaceBaseline.avg_S;
      referenceType = `同种族原版均值（${sameRaceBaseline.commanders_sample.join(", ")}）`;
    } else {
      reference = officialBaseline.overall_avg_S;
      referenceType = `原版整体均值（${officialSampleCommanders.length} 位）`;
    }

    const ratio = reference > 0 ? metrics.avg_S / reference : 0;
    const deltaS = metrics.avg_S - reference;

    // 基础系数：根据 ratio 决定
    let baseAdjust = 1.0;
    let direction = "保持";
    let severity = "正常";
    if (ratio > 5) {
      baseAdjust = 1.30; direction = "nerf"; severity = "严重";
    } else if (ratio > 3) {
      baseAdjust = 1.25; direction = "nerf"; severity = "重度";
    } else if (ratio > 2) {
      baseAdjust = 1.20; direction = "nerf"; severity = "中度";
    } else if (ratio > 1.3) {
      baseAdjust = 1.12; direction = "nerf"; severity = "轻度";
    } else if (ratio > 1.1) {
      baseAdjust = 1.05; direction = "nerf"; severity = "微调";
    } else if (ratio < 0.7) {
      baseAdjust = 0.85; direction = "buff"; severity = "中度";
    } else if (ratio < 0.85) {
      baseAdjust = 0.92; direction = "buff"; severity = "轻度";
    }

    // 离群率修正：nerf 且离群率高时加强，buff 且离群率低时减弱
    const outlierRate = s.outlier_rate || 0;
    let outlierMod = 1.0;
    if (direction === "nerf" && outlierRate > 0.25) outlierMod = 1.05;
    else if (direction === "buff" && outlierRate < 0.05) outlierMod = 0.95;

    const finalAdjust = Number((baseAdjust * outlierMod).toFixed(3));

    patchPlan.push({
      commander: cmdr,
      commander_zh: COMMANDER_NAMES_ZH[cmdr] || cmdr,
      race,
      race_zh: RACE_ZH[race] || race,
      grade: s.grade || "N/A",
      unit_count: metrics.unit_count,
      avg_S: metrics.avg_S,
      median_S: metrics.median_S,
      max_S: metrics.max_S,
      outlier_rate: outlierRate,
      reference_value: Number(reference.toFixed(3)),
      reference_type: referenceType,
      delta_S: Number(deltaS.toFixed(3)),
      ratio: Number(ratio.toFixed(3)),
      direction,
      severity,
      base_adjust: baseAdjust,
      outlier_modifier: outlierMod,
      final_adjust: finalAdjust,
      reason: `avg_S=${metrics.avg_S.toFixed(2)} vs 参照=${reference.toFixed(2)}（${ratio.toFixed(2)}×，${severity} ${direction}）`
    });
  }

  // 按 ratio 降序
  patchPlan.sort((a, b) => b.ratio - a.ratio);

  // === 3. 单位级细粒度调整（仅 Alenger3，基于 Mengsk vs Alenger3 专项对比） ===
  console.log("[patch] 加载单位级细粒度调整...");
  const unitLevelPatches = [];
  if (mengskVsAlenger3?.patch_suggestions) {
    for (const s of mengskVsAlenger3.patch_suggestions) {
      unitLevelPatches.push({
        commander: "Alenger3",
        commander_zh: COMMANDER_NAMES_ZH["Alenger3"],
        unit_id: s.alenger3_unit,
        unit_zh: s.alenger3_zh,
        reference_commander: "Mengsk",
        reference_unit_id: s.mengsk_reference,
        reference_unit_zh: s.mengsk_zh,
        role: s.fingerprint,
        alenger3_S: s.alenger3_S,
        mengsk_S: s.mengsk_S,
        S_ratio: s.S_ratio,
        severity: s.severity,
        cost_adjust: s.cost_adjust,
        reason: s.reason
      });
    }
  }

  // === 4. 整体统计 ===
  const patchSummary = {
    official_baseline: officialBaseline,
    alenger_commander_count: patchPlan.length,
    nerf_count: patchPlan.filter(p => p.direction === "nerf").length,
    buff_count: patchPlan.filter(p => p.direction === "buff").length,
    hold_count: patchPlan.filter(p => p.direction === "保持").length,
    unit_level_patch_count: unitLevelPatches.length,
    overall_avg_ratio: patchPlan.length > 0
      ? Number((patchPlan.reduce((s, p) => s + p.ratio, 0) / patchPlan.length).toFixed(3))
      : 0,
    overall_max_ratio: patchPlan.length > 0
      ? Math.max(...patchPlan.map(p => p.ratio))
      : 0
  };

  // === 写 JSON ===
  console.log("[patch] 写入 balance-patch-plan.json...");
  await mkdir(OUTPUT_DIR, { recursive: true });
  await writeFile(
    join(OUTPUT_DIR, "balance-patch-plan.json"),
    JSON.stringify({
      schema_version: 1,
      generated_at: new Date().toISOString(),
      summary: patchSummary,
      official_baseline: officialBaseline,
      commander_level_patches: patchPlan,
      unit_level_patches: unitLevelPatches
    }, null, 2),
    "utf8"
  );

  // === 写 Markdown ===
  console.log("[patch] 写入 balance-patch-plan.md...");
  const md = [];
  md.push("# SC2 起义指挥官平衡补丁方案 v1");
  md.push("");
  md.push(`**生成时间**：${new Date().toISOString()}`);
  md.push(`**基线**：原版 18 位指挥官（${officialBaseline.commander_count_sample} 位样本充足 + ${officialBaseline.commander_count_excluded} 位样本不足）`);
  md.push(`**目标**：将起义 12 位指挥官的 avg_S 收敛到原版基线的 0.85× ~ 1.15× 范围内`);
  md.push(`**结论**：${patchSummary.nerf_count} 位 nerf，${patchSummary.buff_count} 位 buff，${patchSummary.hold_count} 位保持`);
  md.push("");
  md.push("---");
  md.push("");

  // === 0. 原版基线 ===
  md.push("## 0. 原版基线（18 位指挥官）");
  md.push("");
  md.push(`原版 18 位指挥官中，**${officialBaseline.commander_count_sample} 位**样本充足（单位数 ≥ 5），构成主基线；**${officialBaseline.commander_count_excluded} 位**样本不足（Swann/Karax/Tychus/Abathur/Zeratul），未纳入基线计算。`);
  md.push("");
  md.push(`**原版整体 avg_S 基线**：**${officialBaseline.overall_avg_S}**（基于 ${officialBaseline.commander_count_sample} 位样本充足指挥官）`);
  md.push("");
  md.push("### 0.1 按种族分组基线");
  md.push("");
  md.push("| 种族 | 样本充足指挥官 | 单位总数 | avg_S | median_S | max_S | 排除指挥官 |");
  md.push("|------|----------------|----------|-------|----------|-------|------------|");
  for (const race of ["Terr", "Zerg", "Prot"]) {
    const r = officialByRace[race];
    md.push(`| ${RACE_ZH[race]} (${race}) | ${r.commander_count_sample}（${r.commanders_sample.join("、")}） | ${r.unit_count} | ${fmt(r.avg_S)} | ${fmt(r.median_S)} | ${fmt(r.max_S)} | ${r.commanders_excluded.join("、") || "无"} |`);
  }
  md.push("");
  md.push("### 0.2 原版 18 位指挥官明细");
  md.push("");
  md.push("| 指挥官 | 种族 | 单位数 | avg_S | median_S | max_S | 离群率 | 样本状态 |");
  md.push("|--------|------|--------|-------|----------|-------|--------|----------|");
  for (const c of officialCommanders.sort((a, b) => b.avg_S - a.avg_S)) {
    md.push(`| ${c.commander_zh} (${c.commander}) | ${RACE_ZH[c.race] || c.race} | ${c.unit_count} | ${fmt(c.avg_S)} | ${fmt(c.median_S)} | ${fmt(c.max_S)} | ${(c.outlier_rate * 100).toFixed(1)}% | ${c.insufficient_sample ? "样本不足" : "样本充足"} |`);
  }
  md.push("");
  md.push("**说明**：样本不足的指挥官（Swann/Karax/Tychus/Abathur/Zeratul）单位数为 0 或 < 5，原因是 SC2 合作 mod 中这些指挥官的单位通过 Faction 标签归属于派系（如 Swann 的 Diamondback 标记为 Raider=Raynor），无法通过 mod 数据精确区分。这些指挥官未纳入基线计算，但不影响整体趋势判断。");
  md.push("");
  md.push("---");
  md.push("");

  // === 1. 指挥官级补丁方案 ===
  md.push("## 1. 指挥官级补丁方案（整体造价调整）");
  md.push("");
  md.push(`共 ${patchPlan.length} 位起义指挥官的调整方案，按 S 比率降序排列：`);
  md.push("");
  md.push("| 指挥官 | 种族 | 等级 | 单位数 | avg_S | 参照值 | 参照类型 | Δ S | 比率 | 方向 | 严重程度 | 基础系数 | 离群率修正 | 综合系数 |");
  md.push("|--------|------|------|--------|-------|--------|----------|-----|------|------|----------|----------|------------|----------|");
  for (const p of patchPlan) {
    md.push(`| ${p.commander_zh} | ${p.race_zh} | ${p.grade} | ${p.unit_count} | ${fmt(p.avg_S)} | ${fmt(p.reference_value)} | ${p.reference_type} | ${fmt(p.delta_S)} | ${p.ratio}× | ${p.direction} | ${p.severity} | ×${p.base_adjust} | ×${p.outlier_modifier} | **×${p.final_adjust}** |`);
  }
  md.push("");
  md.push("**调整规则**：");
  md.push("- 比率 > 5：严重 nerf，基础系数 ×1.30");
  md.push("- 比率 > 3：重度 nerf，基础系数 ×1.25");
  md.push("- 比率 > 2：中度 nerf，基础系数 ×1.20");
  md.push("- 比率 > 1.3：轻度 nerf，基础系数 ×1.12");
  md.push("- 比率 > 1.1：微调 nerf，基础系数 ×1.05");
  md.push("- 比率 < 0.7：中度 buff，基础系数 ×0.85");
  md.push("- 比率 < 0.85：轻度 buff，基础系数 ×0.92");
  md.push("- nerf 且离群率 > 25%：综合系数 ×1.05（加强 nerf）");
  md.push("- buff 且离群率 < 5%：综合系数 ×0.95（减弱 buff）");
  md.push("");
  md.push("**应用方式**：将每位起义指挥官所有可生产单位的 `CostResource` 字段（minerals/vespene）乘以综合系数。供应（supply）保持不变。");
  md.push("");
  md.push("---");
  md.push("");

  // === 2. 单位级细粒度补丁方案 ===
  md.push("## 2. 单位级细粒度补丁方案（仅 Alenger3，基于 Mengsk vs Alenger3 专项对比）");
  md.push("");
  md.push(`共 ${unitLevelPatches.length} 条单位级 nerf 建议，按 S 比率降序排列：`);
  md.push("");
  md.push("| 起义单位 | 蒙斯克参照 | 角色 | 起义 S | 蒙斯克 S | S 比率 | 严重程度 | 单位级系数 | 理由 |");
  md.push("|----------|------------|------|--------|----------|---------|----------|------------|------|");
  for (const u of unitLevelPatches) {
    md.push(`| ${u.unit_zh} | ${u.reference_unit_zh} | ${u.role} | ${fmt(u.alenger3_S)} | ${fmt(u.mengsk_S)} | ${u.S_ratio}× | ${u.severity} | ×${u.cost_adjust} | ${u.reason} |`);
  }
  md.push("");
  md.push("**应用方式**：在指挥官级综合系数（×1.20）的基础上，对这些单位的 CostResource 额外乘以单位级系数。最终造价 = 原造价 × 指挥官综合系数 × 单位级系数。");
  md.push("");
  md.push("**注意事项**：");
  md.push("- 相似单位配对基于角色指纹和造价最接近原则匹配，可能存在误配，应用时需人工复核");
  md.push("- 蒙斯克原版部分单位（如 GhostMengsk、BattlecruiserMengsk）的 DPS=0 是因为武器数据未在 mod 中完整定义，实际游戏中这些单位有正常 DPS，对应的 S 比率可能被高估");
  md.push("- 起义 3 的英雄单位（如 百星号、奥古斯都的骄傲）S 值极高，但英雄单位的平衡需额外考虑其获取条件和操作复杂度，不宜直接按 S 值 nerf");
  md.push("");
  md.push("---");
  md.push("");

  // === 3. 应用顺序与验证 ===
  md.push("## 3. 应用顺序与验证");
  md.push("");
  md.push("### 3.1 应用顺序");
  md.push("");
  md.push('1. **第一层（指挥官级）**：按本方案「指挥官级补丁方案」表，将每位起义指挥官所有单位的 CostResource 乘以综合系数');
  md.push('2. **第二层（单位级）**：按本方案「单位级细粒度补丁方案」表，对 Alenger3 的特定单位额外乘以单位级系数');
  md.push('3. **第三层（手动调整）**：参照 mengsk-vs-alenger3.md 的「相似单位配对」表，人工复核起义单位 S 值不超过蒙斯克同定位单位的 1.5×');
  md.push("");
  md.push("### 3.2 验证方法");
  md.push("");
  md.push("1. 应用补丁后，重新运行 official-extract.mjs 和 metrics.mjs，更新 units-scored.json");
  md.push("2. 重新运行 compare-report.mjs，检查起义指挥官 avg_S 是否收敛到原版基线的 0.85× ~ 1.15× 范围内");
  md.push("3. 重新运行 mengsk-vs-alenger3.mjs，检查 Alenger3 的相似单位配对 S 比率是否收敛到 1.5× 以内");
  md.push("4. 进图实际测试，确认起义指挥官的实战强度与原版指挥官接近");
  md.push("");
  md.push("### 3.3 预期效果");
  md.push("");
  md.push(`应用本方案后，预期起义指挥官整体 avg_S 从当前 **${patchSummary.overall_avg_ratio}×** 原版基线，收敛到 **1.0× ± 0.15×** 范围内。`);
  md.push("");
  md.push("---");
  md.push("");

  // === 4. 关键发现 ===
  md.push("## 4. 关键发现");
  md.push("");
  md.push("### 4.1 整体偏差");
  md.push("");
  md.push(`- **起义整体 avg_S 比率**：${patchSummary.overall_avg_ratio}× 原版基线`);
  md.push(`- **起义最高 avg_S 比率**：${patchSummary.overall_max_ratio}×（${patchPlan[0]?.commander_zh || "N/A"}）`);
  md.push(`- **nerf 数量**：${patchSummary.nerf_count} 位`);
  md.push(`- **buff 数量**：${patchSummary.buff_count} 位`);
  md.push(`- **单位级 nerf 数量**：${patchSummary.unit_level_patch_count} 条（仅 Alenger3）`);
  md.push("");
  md.push("### 4.2 偏强指挥官（建议 nerf）");
  md.push("");
  for (const p of patchPlan.filter(p => p.direction === "nerf")) {
    md.push(`- **${p.commander_zh}**：avg_S=${fmt(p.avg_S)}，参照 ${p.reference_type}=${fmt(p.reference_value)}（${p.ratio}×，${p.severity}），综合系数 ×${p.final_adjust}`);
  }
  md.push("");
  md.push("### 4.3 偏弱指挥官（建议 buff）");
  md.push("");
  const buffList = patchPlan.filter(p => p.direction === "buff");
  if (buffList.length === 0) {
    md.push("- 无");
  } else {
    for (const p of buffList) {
      md.push(`- **${p.commander_zh}**：avg_S=${fmt(p.avg_S)}，参照 ${p.reference_type}=${fmt(p.reference_value)}（${p.ratio}×，${p.severity}），综合系数 ×${p.final_adjust}`);
    }
  }
  md.push("");
  md.push("### 4.4 与原版持平的指挥官");
  md.push("");
  const holdList = patchPlan.filter(p => p.direction === "保持");
  if (holdList.length === 0) {
    md.push("- 无");
  } else {
    for (const p of holdList) {
      md.push(`- **${p.commander_zh}**：avg_S=${fmt(p.avg_S)}，参照 ${p.reference_type}=${fmt(p.reference_value)}（${p.ratio}×）`);
    }
  }
  md.push("");
  md.push("---");
  md.push("");

  // === 5. 局限性说明 ===
  md.push("## 5. 局限性说明");
  md.push("");
  md.push("### 5.1 原版基线局限");
  md.push("");
  md.push(`原版 18 位指挥官中，仅 ${officialBaseline.commander_count_sample} 位样本充足，构成主基线。剩余 ${officialBaseline.commander_count_excluded} 位（Swann/Karax/Tychus/Abathur/Zeratul）由于 SC2 合作 mod 中单位归属通过 Faction 标签管理，无法通过 mod 数据精确区分，未纳入基线计算。`);
  md.push("");
  md.push("**影响**：");
  md.push("- 人族基线：包含 Raynor(3 单位)/Nova(19)/Mengsk(25)/Horner(19)/Stetmann(40) 等 5 位，但 Swann 缺失");
  md.push("- 异虫基线：包含 Kerrigan(10)/Zagara(6)/Stukov(47)/Dehaka(43) 等 4 位，但 Abathur 缺失");
  md.push("- 星灵基线：包含 Alarak(3)/Vorazun(3)/Artanis(4)/Fenix(15) 等 4 位，但 Karax/Zeratul 缺失");
  md.push("");
  md.push("**缓解措施**：基线已覆盖各派系的主要单位类型，足以反映原版整体强度水平。后续可通过手动维护 18 位指挥官的单位 ID 列表来补全基线。");
  md.push("");
  md.push("### 5.2 单位级 nerf 局限");
  md.push("");
  md.push("当前仅对 Alenger3（疯批帝国）进行了单位级 nerf 分析，参照对象为原版 Mengsk（蒙斯克）。其他起义指挥官的单位级 nerf 需手动选择参照对象：");
  md.push("");
  md.push("| 起义指挥官 | 建议参照原版指挥官 | 理由 |");
  md.push("|------------|-------------------|------|");
  md.push("| Alenger1（人族） | Raynor / Horner | 同为人族通用风格 |");
  md.push("| Alenger2（异虫） | Kerrigan / Zagara | 同为异虫通用风格 |");
  md.push("| Alenger3（人族·蒙斯克风） | Mengsk（已完成） | 设计风格明显参考蒙斯克 |");
  md.push("| Alenger4（星灵） | Alarak / Artanis | 同为星灵通用风格 |");
  md.push("| Alenger6（异虫·阿巴瑟风） | Abathur | 设计风格明显参考阿巴瑟（但 Abathur 无数据，可用 Kerrigan 替代） |");
  md.push("| Alenger7（人族） | Nova / Raynor | 同为人族通用风格 |");
  md.push("| Alenger8（星灵） | Fenix / Vorazun | 同为星灵通用风格 |");
  md.push("| Alenger9（异虫） | Stukov / Dehaka | 同为异虫通用风格 |");
  md.push("| Alenger12（星灵） | Artanis / Vorazun | 同为星灵通用风格 |");
  md.push("| Alenger13（星灵·蒙斯克风） | Mengsk / Artanis | 设计风格部分参考蒙斯克 |");
  md.push("");
  md.push("### 5.3 公式局限");
  md.push("");
  md.push("S 值公式：`S = (EHP × DPS + skill_value) / cost_normalized`");
  md.push("");
  md.push("**已知问题**：");
  md.push("- 部分原版单位（如 GhostMengsk、BattlecruiserMengsk）的 DPS=0，因为武器数据未在 mod 中完整定义，实际游戏中这些单位有正常 DPS");
  md.push("- 英雄单位（如百星号、奥古斯都的骄傲）S 值极高，但英雄单位的平衡需额外考虑其获取条件和操作复杂度");
  md.push("- skill_value 估算粗略，未涵盖所有技能（如召唤、增益、控制等）");
  md.push("");

  await writeFile(join(OUTPUT_DIR, "balance-patch-plan.md"), md.join("\n"), "utf8");

  console.log("[patch] === 完成 ===");
  console.log(`[patch] 输出目录: ${OUTPUT_DIR}`);
  console.log(`[patch] 指挥官级补丁: ${patchPlan.length} 条（${patchSummary.nerf_count} nerf, ${patchSummary.buff_count} buff）`);
  console.log(`[patch] 单位级补丁: ${unitLevelPatches.length} 条（仅 Alenger3）`);
  console.log(`[patch] 整体比率: ${patchSummary.overall_avg_ratio}× 原版基线`);
}

main().catch(err => {
  console.error("[patch] FATAL:", err);
  console.error(err.stack);
  process.exit(1);
});
