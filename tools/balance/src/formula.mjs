// src/formula.mjs
// 公式 v4 评分 + 离群判定 + 克制矩阵
//
// 公式核心：
//   V_scenario  = (DPS_scenario × EHP × range_factor + Skill_value) × role_modifier
//   S_scenario  = V_scenario / C_normalized
//   S           = max(S_general, max(S_specialized) × 0.85, S_tank × 0.85)
//
// 离群：
//   z_internal = (S - μ_group) / σ_group   按种族+定位分组
//   z_official = (S - μ_official_group) / σ_official_group
//
// 克制矩阵（简化版）：
//   efficiency = DPS_attacker_vs_defender / (EHP_defender / C_attacker)
//   severity: extreme (efficiency > 3σ) | strong (>2σ) | normal

import { classifyRoles } from "./metrics.mjs";

// 计算 V_scenario（单场景价值）
function computeScenarioValue(dps, ehp, rangeFactor, skillValue, roleModifier) {
  return (dps * ehp * rangeFactor + skillValue) * roleModifier;
}

// 计算单单位全部场景 + S
export function scoreUnit(unit, weights) {
  const ehp = unit.ehp;
  const rf = unit.range_factor;
  const sv = unit.skill_value;
  const rm = unit.role_modifier;

  // 注意：vs_light 场景需叠加 splash_factor（已隐含在 dps_light 里）
  const dps_general = unit.dps_general;
  const dps_light = unit.dps_light;
  const dps_armored = unit.dps_armored;
  const dps_massive = unit.dps_massive;
  const dps_air = unit.dps_air;

  const V_general = computeScenarioValue(dps_general, ehp, rf, sv, rm);
  const V_vs_light = computeScenarioValue(dps_light, ehp, rf, sv, rm);
  const V_vs_armored = computeScenarioValue(dps_armored, ehp, rf, sv, rm);
  const V_vs_air = computeScenarioValue(dps_air, ehp, rf, sv, rm);
  const V_vs_massive = computeScenarioValue(dps_massive, ehp, rf, sv, rm);
  // V_tank: DPS 权重 0.3, skill 0.5
  const V_tank = (ehp * rf * 0.3 + sv * 0.5) * rm;

  const C = unit.cost_normalized;
  if (!C || C <= 0) {
    // 无造价：返回 0 分（一般会被过滤）
    return {
      V_general: 0,
      V_vs_light: 0,
      V_vs_armored: 0,
      V_vs_air: 0,
      V_vs_massive: 0,
      V_tank: 0,
      S_general: 0,
      S_vs_light: 0,
      S_vs_armored: 0,
      S_vs_air: 0,
      S_vs_massive: 0,
      S_tank: 0,
      S: 0,
      primary_scenario: "unknown"
    };
  }

  const S_general = V_general / C;
  const S_vs_light = V_vs_light / C;
  const S_vs_armored = V_vs_armored / C;
  const S_vs_air = V_vs_air / C;
  const S_vs_massive = V_vs_massive / C;
  const S_tank = V_tank / C;

  const specializedMax = Math.max(S_vs_light, S_vs_armored, S_vs_air, S_vs_massive);
  const specializedDiscount = weights.scenario_discount.specialized;
  const tankDiscount = weights.scenario_discount.tank;

  const S = Math.max(
    S_general,
    specializedMax * specializedDiscount,
    S_tank * tankDiscount
  );

  // 主要场景（用于报告）
  let primary = "generalist";
  let primaryVal = S_general;
  if (S_vs_light > primaryVal && S_vs_light * specializedDiscount >= S) primary = "anti_light";
  if (S_vs_armored > primaryVal && S_vs_armored * specializedDiscount >= S) primary = "anti_armored";
  if (S_vs_air > primaryVal && S_vs_air * specializedDiscount >= S) primary = "anti_air";
  if (S_vs_massive > primaryVal && S_vs_massive * specializedDiscount >= S) primary = "anti_massive";
  if (S_tank * tankDiscount >= S) primary = "tank";

  return {
    V_general,
    V_vs_light,
    V_vs_armored,
    V_vs_air,
    V_vs_massive,
    V_tank,
    S_general,
    S_vs_light,
    S_vs_armored,
    S_vs_air,
    S_vs_massive,
    S_tank,
    S,
    primary_scenario: primary
  };
}

// 给一组已 score 的单位，计算分组统计（按 race × role 分组）
export function computeGroupStatistics(scoredUnits, weights) {
  // 先给每个 unit 标 role（含 tank，需要二次扫描）
  // 第一遍：标非 tank 的 role
  const enriched = scoredUnits.map((u) => {
    const roles = classifyRoles(u, weights);
    return { ...u, roles_pre: roles };
  });

  // 计算每组（race × role）的 S 均值/标准差（不含 tank，需先有粗分组）
  // tank 标签需要 EHP/C 和 DPS/C 的相对值，这里采用同 race × generalist 作为参考组
  // 简化：先按 race 分组，再算 μ_cost_ratio 和 μ_dps_ratio（用于判定 tank）

  // 收集所有 role 字符串作为分组键
  function groupKey(u, role) {
    return `${u.race}::${role}`;
  }

  // 第一遍：tank 判定需基于 cost_ratio 与 dps_ratio 与组均值的比较
  // 这里采用 race 分组，组内计算 EHP/C 和 DPS/C 的均值
  const raceBuckets = new Map();
  for (const u of enriched) {
    if (!raceBuckets.has(u.race)) raceBuckets.set(u.race, []);
    raceBuckets.get(u.race).push(u);
  }
  const raceStats = new Map();
  for (const [race, arr] of raceBuckets.entries()) {
    const ehpCosts = arr.map((u) => (u.cost_normalized > 0 ? u.ehp / u.cost_normalized : 0));
    const dpsCosts = arr.map((u) => (u.cost_normalized > 0 ? u.dps_general / u.cost_normalized : 0));
    const ehpCostMean = mean(ehpCosts);
    const dpsCostMean = mean(dpsCosts);
    raceStats.set(race, { ehpCostMean, dpsCostMean });
  }

  // 第二遍：补 tank 标签
  for (const u of enriched) {
    const stat = raceStats.get(u.race);
    const roles = [...u.roles_pre];
    if (stat && u.cost_normalized > 0) {
      const ehpRatio = u.ehp / u.cost_normalized;
      const dpsRatio = u.dps_general / u.cost_normalized;
      if (
        ehpRatio > stat.ehpCostMean * weights.tank_role.ehp_to_cost_ratio_factor &&
        dpsRatio < stat.dpsCostMean * weights.tank_role.dps_to_cost_ratio_factor
      ) {
        roles.push("tank");
      }
    }
    if (roles.length === 0) roles.push("generalist");
    u.roles = roles;
    u.primary_role = u.roles[0]; // 用于分组（多 role 单位会出现在多个分组里）
  }

  // 第三遍：按 (race × role) 分组，每组算 S 的 μ / σ
  // 一个单位有多个 role 时进入多个分组
  const groupBuckets = new Map();
  for (const u of enriched) {
    for (const r of u.roles) {
      const key = `${u.race}::${r}`;
      if (!groupBuckets.has(key)) groupBuckets.set(key, []);
      groupBuckets.get(key).push(u);
    }
  }

  const groupStats = {};
  for (const [key, arr] of groupBuckets.entries()) {
    const sValues = arr.map((u) => u.S).filter((v) => isFinite(v) && v > 0);
    if (sValues.length < 2) {
      groupStats[key] = { mu: mean(sValues), sigma: 0, n: sValues.length };
    } else {
      groupStats[key] = { mu: mean(sValues), sigma: stdev(sValues), n: sValues.length };
    }
  }

  return { enriched, groupStats };
}

// 计算 z-score：对每个 unit，按其 race × primary_role 找 groupStats，计算 z_internal
// z_official 仅在官方分组有足够样本（n>=5 且 sigma>0）时才计算，否则置 0。
// 这是为了避免"官方仅有 Mengsk+Stetmann 2 个指挥官、每组样本极少"导致 z_official 噪声爆炸。
export function computeZScores(scoredUnits, groupStats, officialGroupStats, opts = {}) {
  const minOfficialN = opts.minOfficialN ?? 5;
  const out = [];
  for (const u of scoredUnits) {
    const key = `${u.race}::${u.primary_role}`;
    const g = groupStats[key] || { mu: u.S, sigma: 0, n: 1 };
    const z_internal = g.sigma > 0 ? (u.S - g.mu) / g.sigma : 0;

    let z_official = 0;
    if (officialGroupStats && officialGroupStats[key]) {
      const og = officialGroupStats[key];
      if (og.n >= minOfficialN && og.sigma > 0) {
        z_official = (u.S - og.mu) / og.sigma;
      }
    }

    out.push({
      ...u,
      group_key: key,
      group_n: g.n,
      group_mu: g.mu,
      group_sigma: g.sigma,
      z_internal,
      z_official
    });
  }
  return out;
}

// 离群单位筛选（|z_internal| > 阈值 或 |z_official| > 阈值）
// 排序优先按 |z_internal|；z_official 仅作为补充信号
export function findOutliers(unitsWithZ, weights) {
  const thr = weights.outlier.z_threshold;
  return unitsWithZ
    .filter((u) => Math.abs(u.z_internal) > thr || Math.abs(u.z_official) > thr)
    .map((u) => ({
      id: u.id,
      commander: u.commander,
      race: u.race,
      primary_role: u.primary_role,
      roles: u.roles,
      S: u.S,
      cost_normalized: u.cost_normalized,
      ehp: u.ehp,
      dps_general: u.dps_general,
      z_internal: u.z_internal,
      z_official: u.z_official,
      max_z: Math.max(Math.abs(u.z_internal), Math.abs(u.z_official)),
      primary_z: u.z_internal, // 用于排序的主 z
      primary_scenario: u.primary_scenario
    }))
    .sort((a, b) => {
      // 主排序：|z_internal| 降序；次排序：|z_official| 降序
      const aInternal = Math.abs(a.z_internal);
      const bInternal = Math.abs(b.z_internal);
      if (aInternal !== bInternal) return bInternal - aInternal;
      return Math.abs(b.z_official) - Math.abs(a.z_official);
    });
}

// 补丁建议：仅离群单位，建议新造价 = C × (1 / (1 + 0.15 × z))，收敛到 ±30%
export function suggestPatches(outliers, weights) {
  const zCoeff = weights.patch_suggestion.z_decay_coeff;
  const clampMin = weights.patch_suggestion.clamp_min;
  const clampMax = weights.patch_suggestion.clamp_max;
  return outliers.map((o) => {
    const z = Math.abs(o.z_internal) >= Math.abs(o.z_official) ? o.z_internal : o.z_official;
    // 偏强 -> 加价；偏弱 -> 减价
    const decay = 1 / (1 + zCoeff * z);
    const clamped = Math.min(clampMax, Math.max(clampMin, decay));
    const newCost = Math.round(o.cost_normalized * clamped);
    return {
      id: o.id,
      commander: o.commander,
      race: o.race,
      primary_role: o.primary_role,
      current_cost: o.cost_normalized,
      suggested_cost: newCost,
      cost_ratio: clamped,
      S: o.S,
      z_internal: o.z_internal,
      z_official: o.z_official,
      direction: z > 0 ? "nerf" : "buff"
    };
  });
}

// 克制矩阵：每单位对其最强克制对象 + 全局 Top 10 极端克制
// efficiency = DPS_attacker_vs_defender / (EHP_defender / C_attacker)
// "vs_defender" 取决于 defender 的装甲类型
function dpsOfAttackerVsDefender(attacker, defender) {
  // defender 装甲类型决定使用哪个 DPS 字段
  if (defender.is_light) return Math.max(attacker.dps_general, attacker.dps_light);
  if (defender.is_armored) return Math.max(attacker.dps_general, attacker.dps_armored);
  if (defender.is_massive) return Math.max(attacker.dps_general, attacker.dps_massive);
  if (defender.is_biological) return Math.max(attacker.dps_general, attacker.dps_biological);
  return attacker.dps_general;
}

export function computeCounterMatrix(units, weights) {
  const topN = weights.counter_matrix.top_n;
  const extremeSigma = weights.counter_matrix.severity_extreme_sigma;

  // 仅在能命中对方的对之间计算（避免 N×M 过大时性能问题，但合作单位数有限）
  const allPairs = [];
  const bestPerAttacker = new Map();

  for (const attacker of units) {
    let best = null;
    for (const defender of units) {
      if (attacker.id === defender.id) continue;
      // 必须能打对方所在 plane
      const hitsDefender =
        (defender.is_air && attacker.can_hit_air) ||
        (defender.is_ground && attacker.can_hit_ground) ||
        (!defender.is_air && !defender.is_ground && attacker.can_hit_ground);
      if (!hitsDefender) continue;
      if (defender.ehp <= 0) continue;
      if (attacker.cost_normalized <= 0) continue;
      const dps = dpsOfAttackerVsDefender(attacker, defender);
      if (dps <= 0) continue;
      const efficiency = dps / (defender.ehp / attacker.cost_normalized);
      const pair = {
        attacker_id: attacker.id,
        attacker_commander: attacker.commander,
        defender_id: defender.id,
        defender_commander: defender.commander,
        defender_role: defender.primary_role,
        efficiency
      };
      allPairs.push(pair);
      if (!best || pair.efficiency > best.efficiency) {
        best = pair;
      }
    }
    if (best) bestPerAttacker.set(attacker.id, best);
  }

  // 计算效率均值/标准差
  if (allPairs.length === 0) {
    return {
      per_attacker: [],
      top_n: [],
      severity_thresholds: { extreme: null, strong: null, mean: 0, stdev: 0 }
    };
  }
  const effs = allPairs.map((p) => p.efficiency);
  const mu = mean(effs);
  const sigma = stdev(effs);
  const extremeThr = mu + extremeSigma * sigma;
  const strongThr = mu + 2 * sigma;

  // 标 severity
  for (const p of allPairs) {
    if (p.efficiency >= extremeThr) p.severity = "extreme";
    else if (p.efficiency >= strongThr) p.severity = "strong";
    else p.severity = "normal";
  }

  // Top N
  const topNPairs = [...allPairs]
    .sort((a, b) => b.efficiency - a.efficiency)
    .slice(0, topN);

  return {
    per_attacker: [...bestPerAttacker.values()].sort(
      (a, b) => b.efficiency - a.efficiency
    ),
    top_n: topNPairs,
    severity_thresholds: {
      extreme: extremeThr,
      strong: strongThr,
      mean: mu,
      stdev: sigma
    }
  };
}

// 工具函数
function mean(arr) {
  if (!arr.length) return 0;
  let s = 0;
  for (const v of arr) s += v;
  return s / arr.length;
}

function stdev(arr) {
  if (arr.length < 2) return 0;
  const m = mean(arr);
  let s = 0;
  for (const v of arr) s += (v - m) * (v - m);
  return Math.sqrt(s / (arr.length - 1));
}
