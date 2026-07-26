// src/mod-strength.mjs
// 按指挥官分组评估 mod 强度
//
// 输入：
//   units-scored.json   含 S、z_internal、z_official 等评分
//   outliers.json       离群单位清单
//   baseline-official.json  官方基准池分组统计
//   formula-weights.json    权重（用于读取 z_threshold 等）
//
// 输出：
//   mod-strength.json   结构化数据
//   mod-strength.md     可读报告
//
// 评估维度：
//   1. 基础统计：单位数、S 均值/中位/σ
//   2. 离群分布：nerf/buff 单位数、离群率
//   3. 种族分布：Terr/Prot/Zerg 占比
//   4. 定位分布：generalist/splash/anti_air/tank 等占比
//   5. 资源特征：平均造价、平均 EHP、平均 DPS
//   6. 强度评分：基于 μ_cmdr vs μ_official 偏移 + 离群率 + Top 强势单位数
//   7. 强度等级：S/A/B/C/D 五级
//   8. Top 强势 / 弱势单位

import { readFile, writeFile, mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const balanceRoot = resolve(scriptDir, "..");
const workspaceRoot = resolve(balanceRoot, "..", "..");
const OUTPUT_DIR = resolve(workspaceRoot, "artifacts", "balance", "2026-07-26");

async function readJson(rel) {
  const p = join(OUTPUT_DIR, rel);
  if (!existsSync(p)) {
    throw new Error(`missing input: ${p}`);
  }
  return JSON.parse(await readFile(p, "utf8"));
}

function mean(arr) {
  if (!arr.length) return 0;
  let s = 0;
  for (const v of arr) s += v;
  return s / arr.length;
}

function median(arr) {
  if (!arr.length) return 0;
  const sorted = [...arr].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function stdev(arr) {
  if (arr.length < 2) return 0;
  const m = mean(arr);
  let s = 0;
  for (const v of arr) s += (v - m) * (v - m);
  return Math.sqrt(s / (arr.length - 1));
}

function pct(arr, p) {
  if (!arr.length) return 0;
  const sorted = [...arr].sort((a, b) => a - b);
  const idx = Math.min(sorted.length - 1, Math.max(0, Math.floor((p / 100) * sorted.length)));
  return sorted[idx];
}

function fmtNum(v, digits = 2) {
  if (v === null || v === undefined || !isFinite(v)) return "N/A";
  if (Math.abs(v) >= 1e6) return v.toExponential(2);
  if (Math.abs(v) >= 1e4) return v.toFixed(0);
  return Number(v).toFixed(digits);
}

// 样本量阈值：低于此值的指挥官标记为 "Insufficient"，不参与正式排名
const MIN_SAMPLE = 5;

// 计算单个指挥官的强度评分
// 评分构成：
//   base_score   = mean(S) 相对官方基准池均值的比例（对小样本惩罚）
//   outlier_pen  = 离群率惩罚（nerf 方向离群越多扣分越多）
//   diversity    = 单位多样性（种族覆盖 + 定位覆盖）
//   final_score  = base_score × (1 - outlier_pen) × (0.8 + 0.2 × diversity)
function evaluateCommander(cmdr, units, outliers, officialGroupStats) {
  const n = units.length;
  if (n === 0) {
    return {
      commander: cmdr,
      unit_count: 0,
      insufficient_sample: true,
      mean_S: 0,
      median_S: 0,
      stdev_S: 0,
      p90_S: 0,
      p10_S: 0,
      nerf_count: 0,
      buff_count: 0,
      outlier_rate: 0,
      race_distribution: {},
      role_distribution: {},
      avg_cost: 0,
      avg_ehp: 0,
      avg_dps: 0,
      avg_z_internal: 0,
      avg_z_official: 0,
      delta_vs_official: 0,
      base_score: 0,
      outlier_penalty: 0,
      diversity_score: 0,
      final_score: 0,
      grade: "D",
      top_strong: [],
      top_weak: [],
      outlier_units: []
    };
  }

  const sArr = units.map((u) => u.S).filter((v) => isFinite(v) && v > 0);
  const zIntArr = units.map((u) => u.z_internal || 0);
  const zOffArr = units.map((u) => u.z_official || 0);

  // 离群单位（仅本指挥官）
  const myOutliers = outliers.filter((o) => o.commander === cmdr);
  const nerfCount = myOutliers.filter((o) => o.z_internal > 0).length;
  const buffCount = myOutliers.filter((o) => o.z_internal < 0).length;
  const outlierRate = myOutliers.length / n;

  // 种族分布
  const raceDist = {};
  for (const u of units) {
    raceDist[u.race] = (raceDist[u.race] || 0) + 1;
  }
  for (const k of Object.keys(raceDist)) {
    raceDist[k] = raceDist[k] / n;
  }

  // 定位分布
  const roleDist = {};
  for (const u of units) {
    roleDist[u.primary_role] = (roleDist[u.primary_role] || 0) + 1;
  }
  for (const k of Object.keys(roleDist)) {
    roleDist[k] = roleDist[k] / n;
  }

  // 资源特征
  const avgCost = mean(units.map((u) => u.cost_normalized || 0));
  const avgEhp = mean(units.map((u) => u.ehp || 0));
  const avgDps = mean(units.map((u) => u.dps_general || 0));

  // 计算与官方基准的偏移
  // 对每个 unit，按其 group_key 找官方基准，计算 S 偏移
  const deltas = [];
  for (const u of units) {
    const og = officialGroupStats[u.group_key];
    if (og && og.n >= 3 && og.mu > 0) {
      deltas.push(u.S - og.mu);
    }
  }
  const deltaVsOfficial = mean(deltas);

  // 评分计算
  // base_score: S 均值相对官方基准池均值的比例
  // 取本指挥官 S 均值 / 官方基准池整体均值
  const officialAllMu = mean(
    Object.values(officialGroupStats)
      .filter((g) => g.n >= 3 && g.mu > 0)
      .map((g) => g.mu)
  );
  const meanS = mean(sArr);
  const baseScore = officialAllMu > 0 ? meanS / officialAllMu : 1;

  // 离群率惩罚：nerf 方向离群是过强信号
  // outlier_penalty = min(0.5, nerf_rate × 2)
  // nerf_rate = nerfCount / n
  const nerfRate = nerfCount / n;
  const outlierPenalty = Math.min(0.5, nerfRate * 2);

  // 多样性：种族覆盖数 / 3 + 定位覆盖数 / 7（最多 1.0）
  const raceCoverage = Math.min(1, Object.keys(raceDist).length / 3);
  const roleCoverage = Math.min(1, Object.keys(roleDist).length / 7);
  const diversityScore = (raceCoverage + roleCoverage) / 2;

  // 样本量不足时标记为 Insufficient，不参与正式排名
  const insufficient = n < MIN_SAMPLE;

  // 最终评分：样本不足时置 0（不参与正式排名）
  const finalScore = insufficient ? 0 : baseScore * (1 - outlierPenalty) * (0.8 + 0.2 * diversityScore);

  // 强度等级
  let grade;
  if (insufficient) grade = "N/A";
  else if (finalScore >= 5) grade = "S";
  else if (finalScore >= 3) grade = "A";
  else if (finalScore >= 1.5) grade = "B";
  else if (finalScore >= 0.8) grade = "C";
  else grade = "D";

  // Top 强势 / 弱势单位（按 S 降序/升序）
  const sortedByS = [...units].sort((a, b) => (b.S || 0) - (a.S || 0));
  const topStrong = sortedByS.slice(0, 5).map((u) => ({
    id: u.id,
    race: u.race,
    primary_role: u.primary_role,
    S: u.S,
    z_internal: u.z_internal,
    z_official: u.z_official,
    cost_normalized: u.cost_normalized
  }));
  const topWeak = sortedByS.slice(-5).reverse().map((u) => ({
    id: u.id,
    race: u.race,
    primary_role: u.primary_role,
    S: u.S,
    z_internal: u.z_internal,
    z_official: u.z_official,
    cost_normalized: u.cost_normalized
  }));

  // 离群单位清单（按 |z| 降序）
  const outlierUnits = [...myOutliers]
    .sort((a, b) => Math.abs(b.z_internal) - Math.abs(a.z_internal))
    .slice(0, 10)
    .map((o) => ({
      id: o.id,
      primary_role: o.primary_role,
      S: o.S,
      cost_normalized: o.cost_normalized,
      z_internal: o.z_internal,
      z_official: o.z_official,
      max_z: o.max_z,
      direction: o.z_internal > 0 ? "nerf" : "buff"
    }));

  return {
    commander: cmdr,
    unit_count: n,
    insufficient_sample: insufficient,
    mean_S: meanS,
    median_S: median(sArr),
    stdev_S: stdev(sArr),
    p90_S: pct(sArr, 90),
    p10_S: pct(sArr, 10),
    nerf_count: nerfCount,
    buff_count: buffCount,
    outlier_rate: outlierRate,
    race_distribution: raceDist,
    role_distribution: roleDist,
    avg_cost: avgCost,
    avg_ehp: avgEhp,
    avg_dps: avgDps,
    avg_z_internal: mean(zIntArr),
    avg_z_official: mean(zOffArr),
    delta_vs_official: deltaVsOfficial,
    base_score: baseScore,
    outlier_penalty: outlierPenalty,
    diversity_score: diversityScore,
    final_score: finalScore,
    grade,
    top_strong: topStrong,
    top_weak: topWeak,
    outlier_units: outlierUnits
  };
}

function buildOfficialGroupStatsMap(baseline) {
  const map = {};
  for (const g of baseline.groups) {
    map[`${g.race}::${g.role}`] = { mu: g.mu, sigma: g.sigma, n: g.n };
  }
  return map;
}

function generateMarkdown(report, weights) {
  const lines = [];
  lines.push(`# SC2 Mod 强度评估报告`);
  lines.push("");
  lines.push(`**生成时间**：${report.generated_at}`);
  lines.push(`**数据源**：${report.alenger_unit_count} 起义单位 + ${report.official_unit_count} 官方基准池单位`);
  lines.push(`**评估维度**：基础统计 / 离群分布 / 多样性 / 与官方基准偏移`);
  lines.push("");
  lines.push("## 1. 评分公式说明");
  lines.push("");
  lines.push("```");
  lines.push("base_score     = mean(S_cmdr) / mean(S_official_baseline)");
  lines.push("outlier_pen    = min(0.5, nerf_rate × 2)   // nerf_rate = nerf_count / unit_count");
  lines.push("diversity      = (race_coverage + role_coverage) / 2");
  lines.push("final_score    = base_score × (1 - outlier_pen) × (0.8 + 0.2 × diversity)");
  lines.push("```");
  lines.push("");
  lines.push("**等级划分**：S(≥5) / A(≥3) / B(≥1.5) / C(≥0.8) / D(<0.8)");
  lines.push("");
  lines.push("**评分逻辑**：");
  lines.push("- `base_score` 反映该指挥官单位整体性价比相对官方基准池的比例（>1 表示偏强）");
  lines.push("- `outlier_pen` 仅惩罚 nerf 方向离群（z_internal > 阈值），buff 方向不惩罚（弱势单位不算强度问题）");
  lines.push("- `diversity` 奖励种族与定位覆盖广度，单一玩法指挥官略降分");
  lines.push("");
  lines.push("## 2. 指挥官强度排名");
  lines.push("");
  lines.push("**注**：单位数 < 5 的指挥官样本不足，标记为 N/A，不参与正式排名（列在表格末尾）。");
  lines.push("");
  lines.push("| 排名 | 指挥官 | 等级 | 单位数 | mean(S) | 离群率 | nerf | buff | base | penalty | diversity | final_score | Δ_vs_official |");
  lines.push("|------|--------|------|--------|---------|--------|------|------|------|---------|-----------|-------------|---------------|");
  let rank = 0;
  report.ranking.forEach((r) => {
    const displayRank = r.insufficient_sample ? "-" : ++rank;
    const flag = r.insufficient_sample ? " ⚠️样本不足" : "";
    lines.push(
      `| ${displayRank} | ${r.commander}${flag} | ${r.grade} | ${r.unit_count} | ${fmtNum(r.mean_S, 2)} | ${(r.outlier_rate * 100).toFixed(1)}% | ${r.nerf_count} | ${r.buff_count} | ${fmtNum(r.base_score, 3)} | ${fmtNum(r.outlier_penalty, 3)} | ${fmtNum(r.diversity_score, 3)} | ${fmtNum(r.final_score, 3)} | ${fmtNum(r.delta_vs_official, 2)} |`
    );
  });
  lines.push("");

  lines.push("## 3. 详细统计");
  lines.push("");
  for (const r of report.ranking) {
    lines.push(`### 3.${report.ranking.indexOf(r) + 1} ${r.commander}（等级 ${r.grade}）`);
    lines.push("");
    lines.push(`- **单位数**：${r.unit_count}`);
    lines.push(`- **S 分布**：mean=${fmtNum(r.mean_S, 2)}, median=${fmtNum(r.median_S, 2)}, σ=${fmtNum(r.stdev_S, 2)}, p10=${fmtNum(r.p10_S, 2)}, p90=${fmtNum(r.p90_S, 2)}`);
    lines.push(`- **离群**：nerf=${r.nerf_count}, buff=${r.buff_count}, 离群率=${(r.outlier_rate * 100).toFixed(1)}%`);
    lines.push(`- **z 均值**：z_internal=${fmtNum(r.avg_z_internal, 3)}, z_official=${fmtNum(r.avg_z_official, 3)}`);
    lines.push(`- **Δ vs 官方基准**：${fmtNum(r.delta_vs_official, 2)}（正=偏强，负=偏弱）`);
    lines.push(`- **资源特征**：avg_cost=${fmtNum(r.avg_cost, 0)}, avg_ehp=${fmtNum(r.avg_ehp, 0)}, avg_dps=${fmtNum(r.avg_dps, 1)}`);
    lines.push(`- **多样性**：diversity_score=${fmtNum(r.diversity_score, 3)}`);
    lines.push("");
    lines.push("**种族分布**：");
    lines.push("");
    lines.push("| 种族 | 占比 |");
    lines.push("|------|------|");
    for (const [race, p] of Object.entries(r.race_distribution).sort((a, b) => b[1] - a[1])) {
      lines.push(`| ${race} | ${(p * 100).toFixed(1)}% |`);
    }
    lines.push("");
    lines.push("**定位分布**：");
    lines.push("");
    lines.push("| 定位 | 占比 |");
    lines.push("|------|------|");
    for (const [role, p] of Object.entries(r.role_distribution).sort((a, b) => b[1] - a[1])) {
      lines.push(`| ${role} | ${(p * 100).toFixed(1)}% |`);
    }
    lines.push("");
    if (r.top_strong.length > 0) {
      lines.push("**Top 5 强势单位**：");
      lines.push("");
      lines.push("| ID | 种族 | 定位 | S | z_internal | z_official | cost |");
      lines.push("|----|------|------|---|------------|------------|------|");
      for (const u of r.top_strong) {
        lines.push(`| ${u.id} | ${u.race} | ${u.primary_role} | ${fmtNum(u.S, 2)} | ${fmtNum(u.z_internal, 2)} | ${fmtNum(u.z_official, 2)} | ${fmtNum(u.cost_normalized, 0)} |`);
      }
      lines.push("");
    }
    if (r.top_weak.length > 0) {
      lines.push("**Top 5 弱势单位**：");
      lines.push("");
      lines.push("| ID | 种族 | 定位 | S | z_internal | z_official | cost |");
      lines.push("|----|------|------|---|------------|------------|------|");
      for (const u of r.top_weak) {
        lines.push(`| ${u.id} | ${u.race} | ${u.primary_role} | ${fmtNum(u.S, 2)} | ${fmtNum(u.z_internal, 2)} | ${fmtNum(u.z_official, 2)} | ${fmtNum(u.cost_normalized, 0)} |`);
      }
      lines.push("");
    }
    if (r.outlier_units.length > 0) {
      lines.push("**离群单位 Top 10（按 |z_internal|）**：");
      lines.push("");
      lines.push("| ID | 定位 | S | cost | z_internal | z_official | max_z | 方向 |");
      lines.push("|----|------|---|------|------------|------------|-------|------|");
      for (const o of r.outlier_units) {
        lines.push(`| ${o.id} | ${o.primary_role} | ${fmtNum(o.S, 2)} | ${fmtNum(o.cost_normalized, 0)} | ${fmtNum(o.z_internal, 2)} | ${fmtNum(o.z_official, 2)} | ${fmtNum(o.max_z, 2)} | ${o.direction} |`);
      }
      lines.push("");
    }
  }

  lines.push("## 4. 整体观察");
  lines.push("");
  // 整体观察自动生成（排除样本不足的指挥官）
  const validRanking = report.ranking.filter((r) => !r.insufficient_sample);
  const insufficientRanking = report.ranking.filter((r) => r.insufficient_sample);
  const totalUnits = validRanking.reduce((s, r) => s + r.unit_count, 0);
  const totalNerf = validRanking.reduce((s, r) => s + r.nerf_count, 0);
  const totalBuff = validRanking.reduce((s, r) => s + r.buff_count, 0);
  const sGrade = validRanking.filter((r) => r.grade === "S").length;
  const aGrade = validRanking.filter((r) => r.grade === "A").length;
  const bGrade = validRanking.filter((r) => r.grade === "B").length;
  const cGrade = validRanking.filter((r) => r.grade === "C").length;
  const dGrade = validRanking.filter((r) => r.grade === "D").length;
  lines.push(`- 有效指挥官数：**${validRanking.length}**（样本量 ≥ ${MIN_SAMPLE}）`);
  lines.push(`- 样本不足指挥官：${insufficientRanking.length ? insufficientRanking.map((r) => `${r.commander}(n=${r.unit_count})`).join(", ") : "无"}`);
  lines.push(`- 总单位数（有效）：**${totalUnits}**`);
  lines.push(`- 总离群单位：**${totalNerf + totalBuff}**（nerf=${totalNerf}, buff=${totalBuff}）`);
  lines.push(`- 等级分布：S=${sGrade}, A=${aGrade}, B=${bGrade}, C=${cGrade}, D=${dGrade}`);
  lines.push("");
  if (sGrade + aGrade > 0) {
    const strong = validRanking.filter((r) => r.grade === "S" || r.grade === "A").map((r) => r.commander).join(", ");
    lines.push(`- **偏强指挥官（S+A 级）**：${strong}`);
  }
  if (dGrade > 0) {
    const weak = validRanking.filter((r) => r.grade === "D").map((r) => r.commander).join(", ");
    lines.push(`- **偏弱指挥官（D 级）**：${weak}`);
  }
  // 最强 / 最弱
  if (validRanking.length > 0) {
    const top = validRanking[0];
    const bottom = validRanking[validRanking.length - 1];
    lines.push(`- **强度榜首**：${top.commander}（final=${fmtNum(top.final_score, 3)}, grade=${top.grade}）`);
    lines.push(`- **强度末位**：${bottom.commander}（final=${fmtNum(bottom.final_score, 3)}, grade=${bottom.grade}）`);
  }
  lines.push("");
  lines.push("## 5. 调整建议");
  lines.push("");
  lines.push("- 对 S/A 级指挥官：优先核查 nerf 方向离群单位（已列入 patch-suggestions.json），按建议造价上调");
  lines.push("- 对 D 级指挥官：检查单位是否过弱（buff 方向离群），考虑下调造价或强化属性");
  lines.push("- 对多样性低的指挥官：核查是否缺少关键定位（如 anti_air / tank），影响战场适应性");
  lines.push("- 注：final_score 仅为公式评估参考，实际调整需结合实战测试与地图适应性");
  lines.push("");
  lines.push("## 6. Caveats");
  lines.push("");
  lines.push("- **base_score 依赖官方基准池**：官方基准池包含 starcoop 共享 mod 全部战斗单位（含通用建筑、Beacon 等噪声），可能导致 base_score 偏高");
  lines.push("- **diversity 仅看种族/定位覆盖**：不评估科技树深度、技能完整性、战术多样性");
  lines.push("- **未评估指挥官技能/大招**：英雄单位单独评分，但不计入指挥官技能强度");
  lines.push("- **Alenger10 缺失 / Alenger11 仅 2 单位**：样本过少，评分不具参考意义");
  lines.push("- **离群率 ≠ 强度**：离群率高反映单位间平衡性差，不一定代表整体偏强");
  lines.push("- **Δ_vs_official 受分组样本量影响**：仅 n>=3 的官方分组才参与计算，部分定位样本不足时偏移可能不准");
  lines.push("");

  return lines.join("\n");
}

async function main() {
  console.log("[mod-strength] 加载数据...");
  const scored = await readJson("units-scored.json");
  const outliersDoc = await readJson("outliers.json");
  const baseline = await readJson("baseline-official.json");
  const weights = await readJson("formula-weights.json");

  const units = scored.units;
  const outliers = outliersDoc.outliers;
  const officialGroupStats = buildOfficialGroupStatsMap(baseline);

  console.log(`[mod-strength] 起义单位: ${units.length}, 离群单位: ${outliers.length}`);

  // 按指挥官分组
  const byCmdr = new Map();
  for (const u of units) {
    if (!byCmdr.has(u.commander)) byCmdr.set(u.commander, []);
    byCmdr.get(u.commander).push(u);
  }
  console.log(`[mod-strength] 指挥官数: ${byCmdr.size}`);

  // 评估每个指挥官
  const rankings = [];
  for (const [cmdr, arr] of byCmdr.entries()) {
    const r = evaluateCommander(cmdr, arr, outliers, officialGroupStats);
    rankings.push(r);
    console.log(`[mod-strength] ${cmdr}: n=${r.unit_count}, grade=${r.grade}, final=${r.final_score.toFixed(3)}, nerf=${r.nerf_count}, buff=${r.buff_count}`);
  }

  // 按 final_score 降序；样本不足的排到最后
  rankings.sort((a, b) => {
    if (a.insufficient_sample !== b.insufficient_sample) {
      return a.insufficient_sample ? 1 : -1;
    }
    return b.final_score - a.final_score;
  });

  const report = {
    schema_version: 1,
    generated_at: new Date().toISOString(),
    alenger_unit_count: units.length,
    official_unit_count: baseline.total_units,
    formula: "final_score = base_score × (1 - outlier_pen) × (0.8 + 0.2 × diversity)",
    grade_thresholds: { S: 5, A: 3, B: 1.5, C: 0.8, D: 0 },
    ranking: rankings
  };

  console.log("[mod-strength] 写入 mod-strength.json...");
  await mkdir(OUTPUT_DIR, { recursive: true });
  await writeFile(join(OUTPUT_DIR, "mod-strength.json"), JSON.stringify(report, null, 2), "utf8");

  console.log("[mod-strength] 写入 mod-strength.md...");
  const md = generateMarkdown(report, weights);
  await writeFile(join(OUTPUT_DIR, "mod-strength.md"), md, "utf8");

  console.log("[mod-strength] === 完成 ===");
  console.log(`[mod-strength] 报告目录: ${OUTPUT_DIR}`);
  console.log("[mod-strength] 强度排名:");
  rankings.forEach((r, i) => {
    console.log(`  ${i + 1}. ${r.commander} [${r.grade}] final=${r.final_score.toFixed(3)} base=${r.base_score.toFixed(3)} pen=${r.outlier_penalty.toFixed(3)} div=${r.diversity_score.toFixed(3)}`);
  });
}

main().catch((err) => {
  console.error("[mod-strength] FATAL:", err);
  console.error(err.stack);
  process.exit(1);
});
