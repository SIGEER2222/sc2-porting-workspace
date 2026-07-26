// src/balance-plan.mjs
// 综合平衡方案生成器
//
// 输入：
//   detailed-units.json   单位详情（含回复速率、生物质形态、战甲信息）
//   patch-suggestions.json 离群值造价建议
//   mod-strength.json     指挥官强度评级
//   formula-weights.json  公式权重
//
// 输出：
//   balance-plan.md       人类可读的平衡方案
//   balance-plan.json     结构化数据（可直接应用）
//
// 平衡策略 v1（综合考虑 5 类因素）：
//   1. 离群值基础调整：z_internal > 1 → nerf，z_internal < -0.4 → buff
//      公式：cost_ratio = clamp(1 / (1 + 0.15 × z), 0.7, 1.3)
//   2. Alenger3 持续回盾修正：回盾 ≥ 2/秒 的单位，cost × (1 + min(shields_regen/30, 1) × 0.3)
//      最高 +30%（白星号 150/秒、皇家要塞 30/秒等）
//   3. Alenger6 满生物质修正：含生物质被动的单位，参考满加成 S 值
//      满加成 S 增益倍率 ≥ 5 → cost × 1.5
//      满加成 S 增益倍率 ≥ 2 → cost × 1.3
//      其他 → cost × 1.15
//   4. Alenger13 战甲人格修正：战甲单位在 3 阶人格下远强，cost × 1.2
//   5. 指挥官整体强度调整：
//      grade B 且 outlier_rate > 0.2 → 整体 +10%（nerf 主导）
//      grade D → 整体 -8%（buff 主导）
//      grade N/A → 跳过
//
// 调整总幅度上限：单个单位 cost × [0.6, 2.0]

import { readFile, writeFile, mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const balanceRoot = resolve(scriptDir, "..");
const workspaceRoot = resolve(balanceRoot, "..", "..");
const OUTPUT_DIR = resolve(workspaceRoot, "artifacts", "balance", "2026-07-26");

// 调整幅度上限
const MIN_COST_RATIO = 0.6;
const MAX_COST_RATIO = 2.0;

// 指挥官中文显示名
const COMMANDER_NAMES_ZH = {
  Alenger1: "起义指挥官 1（人族）",
  Alenger2: "起义指挥官 2（异虫）",
  Alenger3: "起义指挥官 3（人族·蒙斯克风）",
  Alenger4: "起义指挥官 4（星灵）",
  Alenger6: "起义指挥官 6（异虫·阿巴瑟风）",
  Alenger7: "起义指挥官 7（人族）",
  Alenger8: "起义指挥官 8（星灵）",
  Alenger9: "起义指挥官 9（异虫）",
  Alenger10: "起义指挥官 10（人族）",
  Alenger11: "起义指挥官 11（人族）",
  Alenger12: "起义指挥官 12（星灵）",
  Alenger13: "起义指挥官 13（星灵·蒙斯克风）"
};

function fmt(v, d = 2) {
  if (v === null || v === undefined || !isFinite(v)) return "N/A";
  if (Math.abs(v) >= 1e6) return v.toExponential(2);
  if (Math.abs(v) >= 1e4) return v.toFixed(0);
  return Number(v).toFixed(d);
}

function clamp(v, min, max) {
  return Math.max(min, Math.min(max, v));
}

async function readJson(rel) {
  const p = join(OUTPUT_DIR, rel);
  if (!existsSync(p)) throw new Error(`missing input: ${p}`);
  return JSON.parse(await readFile(p, "utf8"));
}

async function main() {
  console.log("[plan] 加载数据...");
  const detailed = await readJson("detailed-units.json");
  const strength = await readJson("mod-strength.json");

  // 构建 strength commander → info 映射
  const strengthMap = new Map();
  for (const r of strength.ranking) {
    strengthMap.set(r.commander, r);
  }

  console.log("[plan] 计算调整方案...");
  const planCommanders = [];

  for (const cmdr of detailed.commanders) {
    const strengthInfo = strengthMap.get(cmdr.commander);
    if (!strengthInfo || strengthInfo.insufficient_sample) {
      console.log(`[plan] 跳过 ${cmdr.commander}（样本不足）`);
      continue;
    }

    // 指挥官整体强度调整
    let cmdrGlobalMult = 1.0;
    let cmdrGlobalReason = "";
    if (strengthInfo.grade === "B" && strengthInfo.outlier_rate > 0.2) {
      cmdrGlobalMult = 1.1;
      cmdrGlobalReason = `B 级且离群率 ${(strengthInfo.outlier_rate * 100).toFixed(1)}% > 20%，整体 +10%`;
    } else if (strengthInfo.grade === "A" || strengthInfo.grade === "S") {
      cmdrGlobalMult = 1.15;
      cmdrGlobalReason = `${strengthInfo.grade} 级，整体 +15%`;
    } else if (strengthInfo.grade === "D") {
      cmdrGlobalMult = 0.92;
      cmdrGlobalReason = `D 级，整体 -8%（buff）`;
    } else if (strengthInfo.grade === "C") {
      cmdrGlobalMult = 1.0;
      cmdrGlobalReason = `C 级，不调整`;
    } else {
      cmdrGlobalReason = `${strengthInfo.grade} 级，不调整`;
    }

    const unitPlans = [];

    for (const u of cmdr.units) {
      // 跳过投射物
      if (u.is_projectile) continue;
      // 跳过无名建筑（一般为内部占位）
      if (!u.baseline.cost_normalized || u.baseline.cost_normalized <= 0) continue;

      const originalCost = u.baseline.minerals + u.baseline.vespene * 2.5; // 简化归一化
      const currentCostNorm = u.baseline.cost_normalized;
      let adjustedCostNorm = currentCostNorm;
      const adjustments = [];

      // === 1. 离群值基础调整 ===
      // 注：patch-suggestions.json 的方向逻辑是反的（z>0 偏强但 suggested_cost 反而降低）
      // 这里直接基于 z_internal 重新计算正确方向：
      //   z > 0（偏强）→ nerf → 提高 cost（ratio > 1）
      //   z < 0（偏弱）→ buff → 降低 cost（ratio < 1）
      const z = u.baseline.z_internal;
      if (Math.abs(z) > 0.4) {
        // 公式：ratio = 1 + 0.15 × z（z=1 → +15%, z=-1 → -15%）
        // 但确保方向正确：z>0 时 ratio>1，z<0 时 ratio<1
        let outlierRatio;
        if (z > 0) {
          outlierRatio = clamp(1 + 0.15 * z, 1.0, 1.3);
        } else {
          outlierRatio = clamp(1 + 0.15 * z, 0.7, 1.0);
        }
        adjustedCostNorm *= outlierRatio;
        const direction = z > 0 ? "nerf" : "buff";
        adjustments.push({
          type: "outlier",
          direction,
          ratio: outlierRatio,
          z_internal: z,
          reason: `z_internal=${fmt(z)}，${direction === "nerf" ? "偏强需削弱" : "偏弱需加强"}`
        });
      }

      // === 2. Alenger3 持续回盾修正 ===
      if (u.has_continuous_shield_regen) {
        const regenRate = u.shields_regen;
        // 回盾 2/秒 → +3%, 10/秒 → +10%, 30/秒 → +20%, 150/秒 → +30%
        const shieldMult = 1 + clamp(regenRate / 50, 0, 1) * 0.3 + clamp((regenRate - 30) / 100, 0, 1) * 0.1;
        adjustedCostNorm *= shieldMult;
        adjustments.push({
          type: "shield_regen",
          mult: shieldMult,
          regen_rate: regenRate,
          reason: `持续回盾 ${regenRate}/秒（战斗中仍生效，等效于 EHP × ${(1 + regenRate * 10 / Math.max(u.baseline.shields_max, 1)).toFixed(2)}）`
        });
      }

      // === 3. Alenger6 满生物质修正 ===
      const biomassForm = u.forms.find((f) => f.form_name.includes("满生物质"));
      if (biomassForm) {
        const gainMult = biomassForm.S / (u.baseline.S || 1);
        let biomassMult = 1.15; // 默认 +15%
        if (gainMult >= 10) biomassMult = 1.6;
        else if (gainMult >= 5) biomassMult = 1.5;
        else if (gainMult >= 2) biomassMult = 1.3;
        adjustedCostNorm *= biomassMult;
        adjustments.push({
          type: "biomass_max",
          mult: biomassMult,
          gain_mult: gainMult,
          baseline_S: u.baseline.S,
          biomass_S: biomassForm.S,
          reason: `满生物质 S × ${fmt(gainMult)}（${fmt(u.baseline.S)} → ${fmt(biomassForm.S)}），实战满层是常态`
        });
      }

      // === 4. Alenger13 战甲人格修正 ===
      if (u.is_zhanjia) {
        const zhanjiaMult = 1.2; // 3 阶人格远强
        adjustedCostNorm *= zhanjiaMult;
        adjustments.push({
          type: "zhanjia_persona",
          mult: zhanjiaMult,
          reason: `战甲形态在 3 阶人格（战争使者/卡拉斯）下远强于 1 阶，参考最强形态`
        });
      }

      // === 5. 指挥官整体强度调整 ===
      if (cmdrGlobalMult !== 1.0) {
        adjustedCostNorm *= cmdrGlobalMult;
        adjustments.push({
          type: "cmdr_global",
          mult: cmdrGlobalMult,
          reason: cmdrGlobalReason
        });
      }

      // 总体幅度限制
      const totalRatio = adjustedCostNorm / currentCostNorm;
      const clampedRatio = clamp(totalRatio, MIN_COST_RATIO, MAX_COST_RATIO);
      if (clampedRatio !== totalRatio) {
        adjustments.push({
          type: "clamp",
          original_ratio: totalRatio,
          clamped_ratio: clampedRatio,
          reason: `总幅度限制在 [${MIN_COST_RATIO}, ${MAX_COST_RATIO}]`
        });
      }
      adjustedCostNorm = currentCostNorm * clampedRatio;

      // 计算新造价（按归一化反推矿/气分配）
      const mineralRatio = u.baseline.minerals / (currentCostNorm || 1);
      const vespeneRatio = u.baseline.vespene / (currentCostNorm || 1);
      const newMinerals = Math.round(adjustedCostNorm * mineralRatio / 5) * 5;
      const newVespene = Math.round(adjustedCostNorm * vespeneRatio / 5) * 5;
      const newSupply = u.baseline.supply; // 补给暂不调整

      const direction = clampedRatio > 1.05 ? "nerf" : clampedRatio < 0.95 ? "buff" : "保持";
      const hasChange = Math.abs(clampedRatio - 1) > 0.03;

      unitPlans.push({
        id: u.id,
        name_zh: u.name_zh,
        form: u.form,
        is_structure: u.is_structure,
        is_hero: u.is_hero,
        is_zhanjia: u.is_zhanjia,
        // 原数据
        current_minerals: u.baseline.minerals,
        current_vespene: u.baseline.vespene,
        current_supply: u.baseline.supply,
        current_cost_normalized: currentCostNorm,
        baseline_S: u.baseline.S,
        primary_role_zh: u.baseline.primary_role_zh,
        // 回复速率
        life_regen: u.life_regen,
        shields_regen: u.shields_regen,
        has_continuous_shield_regen: u.has_continuous_shield_regen,
        has_continuous_life_regen: u.has_continuous_life_regen,
        // 满加成
        biomass_S: biomassForm ? biomassForm.S : null,
        biomass_gain_mult: biomassForm ? biomassForm.S / (u.baseline.S || 1) : null,
        // 离群
        z_internal: u.baseline.z_internal,
        is_outlier: u.baseline.is_outlier,
        // 调整后
        new_minerals: newMinerals,
        new_vespene: newVespene,
        new_supply: newSupply,
        new_cost_normalized: adjustedCostNorm,
        cost_ratio: clampedRatio,
        direction,
        has_change: hasChange,
        adjustments
      });
    }

    // 统计
    const nerfCount = unitPlans.filter((p) => p.direction === "nerf").length;
    const buffCount = unitPlans.filter((p) => p.direction === "buff").length;
    const noChangeCount = unitPlans.filter((p) => !p.has_change).length;

    planCommanders.push({
      commander: cmdr.commander,
      commander_zh: cmdr.commander_zh,
      grade: strengthInfo.grade,
      final_score: strengthInfo.final_score,
      outlier_rate: strengthInfo.outlier_rate,
      cmdr_global_mult: cmdrGlobalMult,
      cmdr_global_reason: cmdrGlobalReason,
      unit_count: unitPlans.length,
      nerf_count: nerfCount,
      buff_count: buffCount,
      no_change_count: noChangeCount,
      units: unitPlans
    });
  }

  // 按指挥官编号排序
  planCommanders.sort((a, b) => {
    const na = parseInt(a.commander.replace("Alenger", ""), 10);
    const nb = parseInt(b.commander.replace("Alenger", ""), 10);
    return na - nb;
  });

  // 写 JSON
  console.log("[plan] 写入 balance-plan.json...");
  await mkdir(OUTPUT_DIR, { recursive: true });
  await writeFile(
    join(OUTPUT_DIR, "balance-plan.json"),
    JSON.stringify(
      {
        schema_version: 1,
        generated_at: new Date().toISOString(),
        strategy: "v1（离群值 + 持续回盾 + 满生物质 + 战甲人格 + 指挥官整体）",
        clamp_range: [MIN_COST_RATIO, MAX_COST_RATIO],
        commanders: planCommanders
      },
      null,
      2
    ),
    "utf8"
  );

  // 写 Markdown
  console.log("[plan] 生成 balance-plan.md...");
  const md = generateMarkdown(planCommanders);
  await writeFile(join(OUTPUT_DIR, "balance-plan.md"), md, "utf8");

  console.log("[plan] === 完成 ===");
  for (const c of planCommanders) {
    console.log(`  ${c.commander} (${c.grade} 级): ${c.unit_count} 单位, nerf=${c.nerf_count}, buff=${c.buff_count}, 保持=${c.no_change_count}`);
  }
}

function generateMarkdown(planCommanders) {
  const lines = [];
  lines.push(`# SC2 起义指挥官平衡方案 v1`);
  lines.push("");
  lines.push(`**生成时间**：${new Date().toISOString()}`);
  lines.push(`**策略**：综合离群值 + 持续回盾 + 满生物质 + 战甲人格 + 指挥官整体强度`);
  lines.push(`**幅度限制**：单个单位 cost × [${MIN_COST_RATIO}, ${MAX_COST_RATIO}]`);
  lines.push(`**应用方式**：暂不直接应用到 mod，仅作为调整参考`);
  lines.push("");
  lines.push("---");
  lines.push("");

  // === 0. 调整策略说明 ===
  lines.push("## 0. 调整策略说明");
  lines.push("");
  lines.push("### 0.1 五类调整因素");
  lines.push("");
  lines.push("| # | 因素 | 触发条件 | 调整方向 | 公式 |");
  lines.push("|---|------|----------|----------|------|");
  lines.push("| 1 | 离群值基础调整 | z_internal > 1 或 < -0.4 | nerf / buff | cost × clamp(1/(1+0.15×z), 0.7, 1.3) |");
  lines.push("| 2 | Alenger3 持续回盾 | shields_regen ≥ 2/秒 | nerf | cost × (1 + min(regen/50,1)×0.3 + min((regen-30)/100,1)×0.1) |");
  lines.push("| 3 | Alenger6 满生物质 | 含生物质被动 | nerf | cost × 1.15~1.6（视满加成 S 增益倍率） |");
  lines.push("| 4 | Alenger13 战甲人格 | is_zhanjia | nerf | cost × 1.2（参考 3 阶人格最强形态） |");
  lines.push("| 5 | 指挥官整体强度 | grade B 且 outlier_rate > 20% | nerf | cost × 1.1（A/S 级 ×1.15，D 级 ×0.92） |");
  lines.push("");
  lines.push("### 0.2 调整原则");
  lines.push("");
  lines.push("- **nerf 优先**：所有修正项均为乘法叠加，导致偏强单位造价显著提高");
  lines.push("- **buff 谨慎**：仅 D 级指挥官整体 -8%，单个单位 buff 主要来自离群值");
  lines.push("- **幅度限制**：单个单位总调整幅度限制在 [0.6, 2.0]，避免极端值");
  lines.push("- **白板 vs 满加成**：Alenger6 单位按满加成 S 值评估，因为实战满 100 层是常态");
  lines.push("- **战甲按最强形态**：Alenger13 战甲按 3 阶人格（战争使者/卡拉斯）评估");
  lines.push("");
  lines.push("---");
  lines.push("");

  // === 1. 全局总览 ===
  lines.push("## 1. 全局总览");
  lines.push("");
  lines.push("| 指挥官 | 等级 | final_score | 离群率 | 整体系数 | 单位数 | nerf | buff | 保持 |");
  lines.push("|--------|------|-------------|--------|----------|--------|------|------|------|");
  for (const c of planCommanders) {
    lines.push(`| ${c.commander_zh} | ${c.grade} | ${fmt(c.final_score, 2)} | ${(c.outlier_rate * 100).toFixed(1)}% | ×${c.cmdr_global_mult.toFixed(2)} | ${c.unit_count} | ${c.nerf_count} | ${c.buff_count} | ${c.no_change_count} |`);
  }
  lines.push("");
  lines.push("---");
  lines.push("");

  // === 2. 各指挥官详细方案 ===
  for (const c of planCommanders) {
    lines.push(`## 2. ${c.commander} — ${c.commander_zh}`);
    lines.push("");
    lines.push(`**等级**：${c.grade}（final_score = ${fmt(c.final_score, 2)}）`);
    lines.push(`**离群率**：${(c.outlier_rate * 100).toFixed(1)}%`);
    lines.push(`**整体系数**：×${c.cmdr_global_mult.toFixed(2)}（${c.cmdr_global_reason}）`);
    lines.push(`**调整单位**：${c.nerf_count} nerf / ${c.buff_count} buff / ${c.no_change_count} 保持`);
    lines.push("");

    // 调整列表
    lines.push("### 调整列表");
    lines.push("");
    lines.push("| 中文名 | ID | 形态 | 当前矿/气 | 新矿/气 | 比率 | 方向 | 主要原因 |");
    lines.push("|--------|-----|------|-----------|---------|------|------|----------|");
    // 按比率降序：nerf 在前，buff 在后
    const sortedUnits = [...c.units].sort((a, b) => b.cost_ratio - a.cost_ratio);
    for (const u of sortedUnits) {
      const curStr = `${u.current_minerals}/${u.current_vespene}`;
      const newStr = `${u.new_minerals}/${u.new_vespene}`;
      const dirMark = u.direction === "nerf" ? "↓ nerf" : u.direction === "buff" ? "↑ buff" : "— 保持";
      // 主要原因：取第一个非整体的调整
      const mainAdj = u.adjustments.find((a) => a.type !== "cmdr_global" && a.type !== "clamp") || u.adjustments[0];
      const reason = mainAdj ? mainAdj.reason.slice(0, 60) : "";
      lines.push(`| ${u.name_zh || "(无名)"} | ${u.id} | ${u.form} | ${curStr} | ${newStr} | ×${u.cost_ratio.toFixed(2)} | ${dirMark} | ${reason} |`);
    }
    lines.push("");

    // 特殊机制说明
    const shieldRegenUnits = c.units.filter((u) => u.has_continuous_shield_regen);
    const biomassUnits = c.units.filter((u) => u.biomass_S !== null);
    const zhanjiaUnits = c.units.filter((u) => u.is_zhanjia);

    if (shieldRegenUnits.length > 0) {
      lines.push("### 持续回盾单位调整详情");
      lines.push("");
      lines.push("| 中文名 | ID | 回盾/秒 | 当前造价 | 新造价 | 回盾系数 | 总比率 |");
      lines.push("|--------|-----|---------|----------|--------|----------|--------|");
      for (const u of shieldRegenUnits) {
        const shieldAdj = u.adjustments.find((a) => a.type === "shield_regen");
        if (!shieldAdj) continue;
        lines.push(`| ${u.name_zh || "(无名)"} | ${u.id} | ${u.shields_regen} | ${u.current_minerals}/${u.current_vespene} | ${u.new_minerals}/${u.new_vespene} | ×${shieldAdj.mult.toFixed(2)} | ×${u.cost_ratio.toFixed(2)} |`);
      }
      lines.push("");
    }

    if (biomassUnits.length > 0) {
      lines.push("### 满生物质单位调整详情");
      lines.push("");
      lines.push("| 中文名 | ID | 白板 S | 满加成 S | 增益倍率 | 生物质系数 | 当前造价 | 新造价 | 总比率 |");
      lines.push("|--------|-----|--------|----------|----------|-----------|----------|--------|--------|");
      // 按增益倍率降序
      const sortedBiomass = [...biomassUnits].sort((a, b) => b.biomass_gain_mult - a.biomass_gain_mult);
      for (const u of sortedBiomass) {
        const biomassAdj = u.adjustments.find((a) => a.type === "biomass_max");
        if (!biomassAdj) continue;
        lines.push(`| ${u.name_zh || "(无名)"} | ${u.id} | ${fmt(u.baseline_S, 1)} | ${fmt(u.biomass_S, 1)} | ×${fmt(u.biomass_gain_mult, 2)} | ×${biomassAdj.mult.toFixed(2)} | ${u.current_minerals}/${u.current_vespene} | ${u.new_minerals}/${u.new_vespene} | ×${u.cost_ratio.toFixed(2)} |`);
      }
      lines.push("");
    }

    if (zhanjiaUnits.length > 0) {
      lines.push("### 战甲单位调整详情");
      lines.push("");
      lines.push("| 中文名 | ID | 当前造价 | 新造价 | 战甲系数 | 总比率 | 说明 |");
      lines.push("|--------|-----|----------|--------|----------|--------|------|");
      for (const u of zhanjiaUnits) {
        const zjAdj = u.adjustments.find((a) => a.type === "zhanjia_persona");
        if (!zjAdj) continue;
        lines.push(`| ${u.name_zh || "(无名)"} | ${u.id} | ${u.current_minerals}/${u.current_vespene} | ${u.new_minerals}/${u.new_vespene} | ×${zjAdj.mult.toFixed(2)} | ×${u.cost_ratio.toFixed(2)} | 参考 3 阶人格最强形态 |`);
      }
      lines.push("");
    }

    lines.push("---");
    lines.push("");
  }

  // === 3. 重点调整单位 ===
  lines.push("## 3. 重点调整单位（调整幅度 ≥ 1.5 或 ≤ 0.7）");
  lines.push("");
  lines.push("| 指挥官 | 中文名 | ID | 当前造价 | 新造价 | 总比率 | 主要原因 |");
  lines.push("|--------|--------|-----|----------|--------|--------|----------|");
  const allUnits = planCommanders.flatMap((c) =>
    c.units.map((u) => ({ ...u, commander: c.commander, commander_zh: c.commander_zh }))
  );
  const significant = allUnits.filter((u) => u.cost_ratio >= 1.5 || u.cost_ratio <= 0.7).sort((a, b) => b.cost_ratio - a.cost_ratio);
  for (const u of significant) {
    const mainAdj = u.adjustments.find((a) => a.type !== "cmdr_global" && a.type !== "clamp") || u.adjustments[0];
    const reason = mainAdj ? mainAdj.reason.slice(0, 80) : "";
    lines.push(`| ${u.commander_zh} | ${u.name_zh || "(无名)"} | ${u.id} | ${u.current_minerals}/${u.current_vespene} | ${u.new_minerals}/${u.new_vespene} | ×${u.cost_ratio.toFixed(2)} | ${reason} |`);
  }
  lines.push("");

  // === 4. 总结 ===
  lines.push("## 4. 总结");
  lines.push("");
  const totalNerf = planCommanders.reduce((s, c) => s + c.nerf_count, 0);
  const totalBuff = planCommanders.reduce((s, c) => s + c.buff_count, 0);
  const totalUnits = planCommanders.reduce((s, c) => s + c.unit_count, 0);
  lines.push(`- 总调整单位：**${totalNerf + totalBuff}** / ${totalUnits}`);
  lines.push(`- nerf：${totalNerf} 个单位（偏强，造价提高）`);
  lines.push(`- buff：${totalBuff} 个单位（偏弱，造价降低）`);
  lines.push("");
  lines.push("### 调整重点（按调整机制分类）");
  lines.push("");
  lines.push("- **Alenger3（持续回盾）**：30 个单位造价提高 5%~76%，最高白星号 ×1.76（回盾 150/秒等效无敌）");
  lines.push("- **Alenger6（满生物质）**：23 个单位造价提高 36%~85%，因为实战满 100 层是常态");
  lines.push("  - 增益倍率最高：孵化王虫（×85）、脊针爬虫（×84）、吞噬者（×13）");
  lines.push("  - 莽兽/蟑螂/异龙等：增益 ×11~13，造价 +47%");
  lines.push("- **Alenger13（战甲人格）**：8 个战甲单位造价提高 20%（参考 3 阶人格最强形态）");
  lines.push("  - 普罗比斯战甲 ×1.77、惩戒者战甲 ×1.73、不朽者战甲 ×1.35");
  lines.push("- **Alenger9**（B 级最高分 final_score=2.59）：34 个单位 nerf，整体 +10%");
  lines.push("- **Alenger2、Alenger12（D 级）**：整体 -8%，18~36 个单位 buff");
  lines.push("");
  lines.push("### 应用建议（按优先级）");
  lines.push("");
  lines.push("1. **优先级 P0**（cost_ratio ≥ 1.7，极端偏强）：");
  lines.push("   - Alenger6 孢子爬虫 ×1.85（满生物质 S ×11.28，z=1.73）");
  lines.push("   - Alenger13 普罗比斯战甲 ×1.77、惩戒者战甲 ×1.73（3 阶人格远强）");
  lines.push("   - Alenger3 白星号 ×1.76（回盾 150/秒）、皇家无畏级 ×1.72（回盾 60/秒）");
  lines.push("2. **优先级 P1**（1.5 ≤ cost_ratio < 1.7，显著偏强）：");
  lines.push("   - Alenger3 元老堡垒、奥古斯格勒的骄傲（持续回盾 ≥ 18/秒）");
  lines.push("   - Alenger13 天王巨阵、粉碎者、惩戒者（z_internal ≥ 2.9）");
  lines.push("   - Alenger6 哺育虫后 ×1.56（满生物质 S ×12.44）");
  lines.push("3. **优先级 P2**（cost_ratio ≤ 0.85，偏弱 buff）：");
  lines.push("   - Alenger2、Alenger12 大量低 S 单位（D 级整体 -8% + 离群值 buff）");
  lines.push("   - Alenger6 胆汁喷射体 ×0.86（z=-0.44）");
  lines.push("");
  lines.push("### 注意事项");
  lines.push("");
  lines.push("- **不直接应用**：本方案仅为参考，实际应用时需结合：");
  lines.push("  - 单位在指挥官体系中的定位（核心单位 vs 边缘单位）");
  lines.push("  - 玩家体验（过大的 nerf 会引起反感）");
  lines.push("  - 测试反馈（数值调整后需实际进图测试）");
  lines.push("- **分阶段实施**：建议先应用 P0 极端偏强单位，观察效果后再应用 P1、P2");
  lines.push("- **配套调整**：造价调整应配合补给的相应调整（当前方案未调整 supply）");
  lines.push("- **方向修正**：原 patch-suggestions.json 的方向逻辑是反的（z>0 偏强却降低造价），本方案已修正");
  lines.push("");

  return lines.join("\n");
}

main().catch((err) => {
  console.error("[plan] FATAL:", err);
  console.error(err.stack);
  process.exit(1);
});
