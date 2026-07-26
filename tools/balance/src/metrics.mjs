// src/metrics.mjs
// 提取单位/武器/效果指标。
// 输出每个战斗单位的：
//   - 基础属性（LifeMax / LifeArmor / ShieldsMax / Race / Speed / Cost / Supply / BuildTime）
//   - 标签（Attributes / FlagArray / PlaneArray）
//   - 武器列表（每武器 Range / Period / Arc / TargetFilters / Hidden / DisplayAttackCount）
//   - DPS 矩阵（vs general / Light / Armored / Massive / Air / Ground）
//   - EHP / range_factor / splash_factor
//   - role_modifier
//   - Skill_value（启发式）
//   - role 标签（splash / anti_light / anti_armored / anti_air / anti_massive / tank / generalist）

import { getArrayValue, getArrayValues } from "./xml-parser.mjs";
import { traceWeaponEffects } from "./effect-tracer.mjs";

const SPLASH_BRACKETS = [
  { max: 1.0, factor: 1.0 },
  { max: 2.0, factor: 1.15 },
  { max: 3.5, factor: 1.30 },
  { max: Infinity, factor: 1.45 }
];

export function splashFactorForRadius(radius) {
  for (const b of SPLASH_BRACKETS) {
    if (radius <= b.max) return b.factor;
  }
  return 1.45;
}

// 标准装甲类型
const ARMOR_TYPES = ["Light", "Armored", "Biological", "Massive", "Psionic", "Structure", "Robotic", "Heroic", "Mechanical"];

// 解析 TargetFilters 字符串
// 格式："allow_list;exclude_list"，allow/exclude 都是逗号分隔
// 返回 { can_hit_ground: bool, can_hit_air: bool }
export function parseTargetFilters(targetFilters) {
  if (!targetFilters) {
    // 默认可打地面也可打空中
    return { can_hit_ground: true, can_hit_air: true };
  }
  const parts = targetFilters.split(";");
  const allowPart = parts[0] || "";
  const excludePart = parts[1] || "";
  const allowTokens = allowPart.split(",").map((s) => s.trim()).filter(Boolean);
  const excludeTokens = excludePart.split(",").map((s) => s.trim()).filter(Boolean);

  // 默认 allowTokens 为空时表示"全部"
  const allowGround = allowTokens.length === 0 || allowTokens.includes("Ground") || allowTokens.includes("Any");
  const allowAir = allowTokens.length === 0 || allowTokens.includes("Air") || allowTokens.includes("Any");

  const notExcludedGround = !excludeTokens.includes("Ground");
  const notExcludedAir = !excludeTokens.includes("Air");

  return {
    can_hit_ground: allowGround && notExcludedGround,
    can_hit_air: allowAir && notExcludedAir
  };
}

// 解析 CostResource 数组 -> { Minerals, Vespene, Supply, BuildTime? }
function parseCostArray(entry) {
  const arr = entry.arrays.CostResource || [];
  const out = { Minerals: 0, Vespene: 0, Supply: 0 };
  for (const item of arr) {
    const idx = item.index;
    const val = parseFloat(item.value) || 0;
    if (idx === "Minerals") out.Minerals = val;
    else if (idx === "Vespene") out.Vespene = val;
    else if (idx === "Supply" || idx === "Food") out.Supply = val;
  }
  // BuildTime 通常在 fields 上
  if (entry.fields.BuildTime) {
    out.BuildTime = parseFloat(entry.fields.BuildTime) || 0;
  } else {
    out.BuildTime = 0;
  }
  return out;
}

// 解析单位武器列表：返回 [{ link, turret, hidden }]
function parseWeaponArray(unitEntry) {
  const arr = unitEntry.arrays.WeaponArray || [];
  return arr
    .filter((w) => w.Link)
    .map((w) => ({
      link: w.Link,
      turret: w.Turret || null,
      hidden: false // 武器自身没有 Hidden；Hidden 在 WeaponData 的 Options 数组里
    }));
}

// 判定武器是否 Hidden（通过 Options index="Hidden" value="1"）
function isWeaponHidden(weaponEntry) {
  const arr = weaponEntry.arrays.Options || [];
  return arr.some((a) => a.index === "Hidden" && a.value === "1");
}

// 计算单个武器对单目标的 DPS（每装甲类型）
function computeWeaponDps(weaponEntry, effectFamily) {
  const range = parseFloat(weaponEntry.fields.Range) || 0;
  const period = parseFloat(weaponEntry.fields.Period) || 0;
  const arc = parseFloat(weaponEntry.fields.Arc) || 0;
  const targetFilters = weaponEntry.fields.TargetFilters || "";
  const displayAttackCount = parseInt(weaponEntry.fields.DisplayAttackCount, 10) || 1;
  const hidden = isWeaponHidden(weaponEntry);

  if (period <= 0) {
    return {
      range,
      period,
      arc,
      target_filters: targetFilters,
      can_hit_ground: parseTargetFilters(targetFilters).can_hit_ground,
      can_hit_air: parseTargetFilters(targetFilters).can_hit_air,
      hidden,
      display_attack_count: displayAttackCount,
      dps_general: 0,
      dps_light: 0,
      dps_armored: 0,
      dps_massive: 0,
      dps_psionic: 0,
      dps_biological: 0,
      max_radius: 0,
      splash_factor: 1.0
    };
  }

  // 追踪 effect 链
  const trace = traceWeaponEffects(weaponEntry, effectFamily);
  const splashFactor = splashFactorForRadius(trace.max_radius);

  // 单次开火对单目标的伤害（不乘 MaxCount；MaxCount 是 Search 命中上限，单目标最多 1 命中）
  // 多个 damage leaf 时，伤害是各 leaf 之和
  const damages = trace.damages;
  let baseAmount = 0;
  let bonusLight = 0;
  let bonusArmored = 0;
  let bonusMassive = 0;
  let bonusPsionic = 0;
  let bonusBiological = 0;

  for (const d of damages) {
    baseAmount += d.amount;
    bonusLight += d.bonus.Light || 0;
    bonusArmored += d.bonus.Armored || 0;
    bonusMassive += d.bonus.Massive || 0;
    bonusPsionic += d.bonus.Psionic || 0;
    bonusBiological += d.bonus.Biological || 0;
  }

  // DPS = (Amount + Bonus) / Period × splash_factor × DisplayAttackCount
  // 注：DisplayAttackCount 通常=1（仅 UI 显示），但若 effect 链未追踪到 damage（如纯逻辑武器），
  //     而武器明确给出 DisplayAttackCount>1，则按"DisplayAttackCount 次独立命中"近似处理。
  const effectiveShots = baseAmount > 0 ? 1 : (displayAttackCount > 1 ? displayAttackCount : 1);

  return {
    range,
    period,
    arc,
    target_filters: targetFilters,
    can_hit_ground: parseTargetFilters(targetFilters).can_hit_ground,
    can_hit_air: parseTargetFilters(targetFilters).can_hit_air,
    hidden,
    display_attack_count: displayAttackCount,
    dps_general: ((baseAmount * effectiveShots) / period) * splashFactor,
    dps_light: (((baseAmount + bonusLight) * effectiveShots) / period) * splashFactor,
    dps_armored: (((baseAmount + bonusArmored) * effectiveShots) / period) * splashFactor,
    dps_massive: (((baseAmount + bonusMassive) * effectiveShots) / period) * splashFactor,
    dps_psionic: (((baseAmount + bonusPsionic) * effectiveShots) / period) * splashFactor,
    dps_biological: (((baseAmount + bonusBiological) * effectiveShots) / period) * splashFactor,
    max_radius: trace.max_radius,
    splash_factor: splashFactor,
    damage_leaf_count: damages.length
  };
}

// 计算单位总 DPS：所有武器的 DPS 之和（Hidden 武器仍计入）
function computeUnitDps(unitEntry, weaponFamily, effectFamily) {
  const weaponLinks = parseWeaponArray(unitEntry);
  const weaponResults = [];
  for (const { link } of weaponLinks) {
    const wEntry = weaponFamily.get(link);
    if (!wEntry) continue;
    const w = computeWeaponDps(wEntry, effectFamily);
    weaponResults.push({ id: link, ...w });
  }

  // 多武器叠加
  const sum = (key) => weaponResults.reduce((acc, w) => acc + (w[key] || 0), 0);
  return {
    weapons: weaponResults,
    dps_general: sum("dps_general"),
    dps_light: sum("dps_light"),
    dps_armored: sum("dps_armored"),
    dps_massive: sum("dps_massive"),
    dps_psionic: sum("dps_psionic"),
    dps_biological: sum("dps_biological"),
    max_range: weaponResults.reduce((acc, w) => Math.max(acc, w.range || 0), 0),
    max_splash_radius: weaponResults.reduce((acc, w) => Math.max(acc, w.max_radius || 0), 0),
    can_hit_ground: weaponResults.some((w) => w.can_hit_ground),
    can_hit_air: weaponResults.some((w) => w.can_hit_air)
  };
}

// 计算 EHP
export function computeEHP(lifeMax, lifeArmor, shieldsMax, isStructure, weights) {
  const armorFactor = 1 + weights.ehp.armor_dr_per_point * (lifeArmor || 0);
  const structurePenalty = isStructure ? weights.ehp.structure_penalty : 1.0;
  return (lifeMax + shieldsMax) * armorFactor * structurePenalty;
}

// 计算 range_factor
export function computeRangeFactor(maxRange, weights) {
  const ref = weights.range_factor.reference_range;
  const per = weights.range_factor.per_range_above_3;
  return 1 + per * Math.max(0, maxRange - ref);
}

// 计算成本归一化
export function computeCostNormalized(cost, weights) {
  const c = weights.cost;
  return (
    (cost.Minerals || 0) * c.minerals_coeff +
    (cost.Vespene || 0) * c.vespene_coeff +
    0.5 * Math.pow(cost.Supply || 0, 2) * c.supply_squared_coeff +
    (cost.BuildTime || 0) * c.buildtime_coeff
  );
}

// 启发式 Skill_value（基于 BehaviorArray Links + 单位 ID）
function computeSkillValue(unitEntry, weights) {
  let skill = 0;
  const haystack = [];
  haystack.push(unitEntry.id || "");
  const behaviorArr = unitEntry.arrays.BehaviorArray || [];
  for (const b of behaviorArr) {
    if (b.Link) haystack.push(b.Link);
  }
  const abilArr = unitEntry.arrays.AbilArray || [];
  for (const a of abilArr) {
    if (a.Link) haystack.push(a.Link);
  }
  const text = haystack.join(" ");
  const matched = new Set();
  for (const [skillKey, keywords] of Object.entries(weights.skill_keywords)) {
    for (const kw of keywords) {
      if (text.includes(kw)) {
        matched.add(skillKey);
        break;
      }
    }
  }
  for (const key of matched) {
    skill += weights.skill_value[key] || 0;
  }
  return { value: skill, matched_skills: [...matched] };
}

// 计算 role_modifier
function computeRoleModifier(unit, weights) {
  const rm = weights.role_modifier;
  if (unit.is_hero) return rm.hero;
  if (unit.is_worker) return rm.worker;
  if (unit.is_structure) return rm.structure;
  const ground = unit.can_hit_ground;
  const air = unit.can_hit_air;
  if (unit.is_air) {
    if (ground && air) return rm.air_dual;
    if (air && !ground) return rm.air_air_only;
    if (ground && !air) return rm.air_ground_only;
    return rm.air_dual;
  } else {
    if (ground && air) return rm.ground_dual;
    return rm.ground_ground_only;
  }
}

// 解析单位 attributes -> { is_armored, is_light, is_biological, is_massive, is_psionic, is_structure, is_robotic, is_heroic, is_mechanical }
function parseUnitAttributes(unitEntry) {
  const arr = unitEntry.arrays.Attributes || [];
  const out = {};
  for (const a of arr) {
    if (a.value !== "1") continue;
    const k = a.index;
    if (k === "Armored") out.is_armored = true;
    else if (k === "Light") out.is_light = true;
    else if (k === "Biological") out.is_biological = true;
    else if (k === "Massive") out.is_massive = true;
    else if (k === "Psionic") out.is_psionic = true;
    else if (k === "Structure") out.is_structure = true;
    else if (k === "Robotic") out.is_robotic = true;
    else if (k === "Heroic") out.is_heroic = true;
    else if (k === "Mechanical") out.is_mechanical = true;
    else if (k === "Worker") out.is_worker = true;
  }
  return out;
}

function parseUnitPlanes(unitEntry) {
  const arr = unitEntry.arrays.PlaneArray || [];
  let isAir = false;
  let isGround = false;
  for (const a of arr) {
    if (a.value !== "1") continue;
    if (a.index === "Air") isAir = true;
    if (a.index === "Ground") isGround = true;
  }
  // SC2 默认 ground
  if (!isAir && !isGround) isGround = true;
  return { is_air: isAir, is_ground: isGround };
}

function parseUnitFlags(unitEntry) {
  const arr = unitEntry.arrays.FlagArray || [];
  let isHero = false;
  let isWorker = false;
  for (const a of arr) {
    if (a.value !== "1") continue;
    if (a.index === "Hero") isHero = true;
    if (a.index === "Worker") isWorker = true;
  }
  return { is_hero_flag: isHero, is_worker_flag: isWorker };
}

/**
 * 主指标提取函数
 * @param {Entry} unitEntry  已合并 parent 的单位 entry
 * @param {Map<string, Entry>} weaponFamily
 * @param {Map<string, Entry>} effectFamily
 * @param {object} weights  公式权重
 * @returns 单位完整指标对象，或 null 表示应跳过
 */
export function extractUnitMetrics(unitEntry, weaponFamily, effectFamily, weights) {
  const id = unitEntry.id;
  const race = unitEntry.fields.Race || "Unknown";

  const lifeMax = parseFloat(unitEntry.fields.LifeMax) || 0;
  const lifeArmor = parseFloat(unitEntry.fields.LifeArmor) || 0;
  const shieldsMax = parseFloat(unitEntry.fields.ShieldsMax) || 0;
  const speed = parseFloat(unitEntry.fields.Speed) || 0;

  const cost = parseCostArray(unitEntry);
  const attrs = parseUnitAttributes(unitEntry);
  const planes = parseUnitPlanes(unitEntry);
  const flags = parseUnitFlags(unitEntry);

  const isHero = flags.is_hero_flag || attrs.is_heroic || false;
  const isStructure = !!attrs.is_structure;
  const isWorker = flags.is_worker_flag || !!attrs.is_worker;

  const dpsData = computeUnitDps(unitEntry, weaponFamily, effectFamily);

  const ehp = computeEHP(lifeMax, lifeArmor, shieldsMax, isStructure, weights);
  const rangeFactor = computeRangeFactor(dpsData.max_range, weights);
  const costNorm = computeCostNormalized(cost, weights);

  const skillInfo = computeSkillValue(unitEntry, weights);

  const unit = {
    id,
    race,
    family: unitEntry.family,
    ctype: unitEntry.ctype,
    parent: unitEntry.parent,
    source: unitEntry.sourceUri,

    life_max: lifeMax,
    life_armor: lifeArmor,
    shields_max: shieldsMax,
    speed,

    minerals: cost.Minerals,
    vespene: cost.Vespene,
    supply: cost.Supply,
    build_time: cost.BuildTime,
    cost_normalized: costNorm,

    is_armored: !!attrs.is_armored,
    is_light: !!attrs.is_light,
    is_biological: !!attrs.is_biological,
    is_massive: !!attrs.is_massive,
    is_psionic: !!attrs.is_psionic,
    is_structure: isStructure,
    is_robotic: !!attrs.is_robotic,
    is_heroic: !!attrs.is_heroic,
    is_mechanical: !!attrs.is_mechanical,
    is_hero: isHero,
    is_worker: isWorker,
    is_air: planes.is_air,
    is_ground: planes.is_ground,

    weapon_count: dpsData.weapons.length,
    weapons: dpsData.weapons,

    dps_general: dpsData.dps_general,
    dps_light: dpsData.dps_light,
    dps_armored: dpsData.dps_armored,
    dps_massive: dpsData.dps_massive,
    dps_psionic: dpsData.dps_psionic,
    dps_biological: dpsData.dps_biological,
    dps_air: dpsData.can_hit_air ? dpsData.dps_general : 0,
    dps_ground: dpsData.can_hit_ground ? dpsData.dps_general : 0,

    can_hit_air: dpsData.can_hit_air,
    can_hit_ground: dpsData.can_hit_ground,

    max_range: dpsData.max_range,
    max_splash_radius: dpsData.max_splash_radius,

    ehp: ehp,
    range_factor: rangeFactor,

    skill_value: skillInfo.value,
    matched_skills: skillInfo.matched_skills,

    behavior_links: (unitEntry.arrays.BehaviorArray || []).map((b) => b.Link).filter(Boolean),
    abil_links: (unitEntry.arrays.AbilArray || []).map((a) => a.Link).filter(Boolean)
  };

  // role_modifier
  unit.role_modifier = computeRoleModifier(unit, weights);

  // 兜底 cost_normalized 防止 0（除法）
  if (!isFinite(unit.cost_normalized) || unit.cost_normalized <= 0) {
    unit.cost_normalized = 0;
  }

  return unit;
}

// 识别单位 role 标签（splash/anti_light/anti_armored/anti_air/anti_massive/tank/generalist）
// tank 标签需要分组统计信息，这里只判定前 5 个；tank 与 generalist 留给 formula 阶段
export function classifyRoles(unit, weights) {
  const roles = [];
  if (unit.max_splash_radius > 1.0) roles.push("splash");
  if (unit.dps_general > 0 && unit.dps_light > unit.dps_general * weights.specialized_role.dps_ratio_threshold) {
    roles.push("anti_light");
  }
  if (unit.dps_general > 0 && unit.dps_armored > unit.dps_general * weights.specialized_role.dps_ratio_threshold) {
    roles.push("anti_armored");
  }
  if (unit.dps_general > 0 && unit.dps_massive > unit.dps_general * weights.specialized_role.dps_ratio_threshold) {
    roles.push("anti_massive");
  }
  if (
    unit.dps_air > 0 &&
    unit.dps_ground <= unit.dps_air * weights.specialized_role.anti_air_ground_dps_threshold_pct
  ) {
    roles.push("anti_air");
  }
  return roles;
}
