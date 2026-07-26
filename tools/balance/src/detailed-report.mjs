// src/detailed-report.mjs
// 详细中文报告生成器：按指挥官列出每个单位/建筑，识别多形态（白板/满加成/战甲人格）
//
// 输入：
//   units-raw.json       原始数值（含 behavior_links）
//   units-scored.json    评分数据
//   各 mod 的 zhCN.SC2Data/LocalizedData/GameStrings.txt
//
// 输出：
//   detailed-report.md   中文详细报告
//   detailed-units.json  结构化数据
//
// 形态识别规则：
//   1. 阿巴瑟（Alenger6）单位含 behavior_links 中带 6shengwuzhi* → 可叠加生物质
//      满生物质（100 层）加成：
//        - LifeMax × 4 (3% × 100 = 300% 加成)
//        - LifeArmor + 4
//        - DPS × 1.994 (攻速乘子 1.25 × 1.2 × 1.16 × 1.1428) + 武器伤害加成 +4/武器
//        - Range + 4
//        - EHP 相应重算
//   2. 蒙斯克（Alenger13）战甲单位（id 含 zhanjia）：
//        - 由英雄核心 13yingxionghexin 通过 13zheyuebianxing5（折跃变形）召唤
//        - 战甲单位数值（血量/护甲/造价）固定，但根据英雄核心当前人格激活不同被动技能
//        - 人格分级：
//          · 1阶（基础）：卡尔达利斯、提拉特
//          · 2阶（中级）：科罗拉里昂、摩约、塔尔达林
//          · 3阶（高级）：战争使者、卡拉斯
//        - 同一战甲在不同人格下 "数据相同但技能完全不同"
//   3. 通用形态后缀：
//        - Burrowed → 潜地形态
//        - Uprooted → 拔起形态
//        - Phasing → 相位形态
//        - Transport → 运输形态
//        - Placement → 放置物
//        - Weapon/Missile → 投射物（应过滤）

import { readFile, writeFile, mkdir } from "node:fs/promises";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const balanceRoot = resolve(scriptDir, "..");
const workspaceRoot = resolve(balanceRoot, "..", "..");
const OUTPUT_DIR = resolve(workspaceRoot, "artifacts", "balance", "2026-07-26");
const MODS_ROOT = resolve(workspaceRoot, "src", "projects", "cmre-porting", "packages", "Mods", "7vs1");

// 阿巴瑟生物质加成常量（基于 BehaviorData.xml 解析）
const BIOMASS_MAX_STACKS = 100;
const BIOMASS_LIFE_MULT = 4;             // 1 + 0.03 × 100
const BIOMASS_ARMOR_ADD = 4;             // 0.04 × 100
const BIOMASS_DAMAGE_ADD_PER_WEAPON = 4; // 0.04 × 100 (DamageDealtUnscaled)
const BIOMASS_RANGE_ADD = 4;             // 0.04 × 100 (RangedWeaponRange)
const BIOMASS_ATTACK_SPEED_MULT = 1.994; // 1.25 × 1.2 × 1.16 × 1.1428

// 指挥官显示名映射
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

// 蒙斯克英雄核心人格分级表（基于 BehaviorData.xml 解析）
// 每个人格激活战甲的不同被动技能
const MENGSK_PERSONAS = {
  // 1阶人格（基础战斗增强）
  kaerdalisi: {
    name_zh: "卡尔达利斯",
    tier: 1,
    tier_zh: "1阶",
    effect_zh: "受到伤害-50%，近战伤害+50%，移动速度+50%；采集效率+200%",
    activated_behaviors: ["13wuweikuangrezheStart", "13kuangnu"],
    activated_skills_zh: ["无畏狂热者（首次攻击触发）", "狂怒（攻速 ×3）"]
  },
  tilate: {
    name_zh: "提拉特",
    tier: 1,
    tier_zh: "1阶",
    effect_zh: "召唤物最大生命值+100%，伤害+100%；召唤物无法手动控制",
    activated_behaviors: [],
    activated_skills_zh: ["召唤物强化"]
  },
  // 2阶人格（场景伤害加成）
  keluolaliang: {
    name_zh: "科罗拉里昂",
    tier: 2,
    tier_zh: "2阶",
    effect_zh: "法术伤害+100%",
    activated_behaviors: [],
    activated_skills_zh: ["法术伤害翻倍"]
  },
  moyue: {
    name_zh: "摩约",
    tier: 2,
    tier_zh: "2阶",
    effect_zh: "对空中单位伤害+100%",
    activated_behaviors: ["13xiangweitongbulichangCaster"],
    activated_skills_zh: ["相位同步立场（远程范围+2）"]
  },
  taerdalin: {
    name_zh: "塔尔达林",
    tier: 2,
    tier_zh: "2阶",
    effect_zh: "对地面单位伤害+100%",
    activated_behaviors: ["13yonghengyasuoxitong", "13yingxiongbuxiu"],
    activated_skills_zh: ["永恒压缩系统", "英雄不朽"]
  },
  // 3阶人格（高级技能）
  kalsi: {
    name_zh: "卡拉斯",
    tier: 3,
    tier_zh: "3阶",
    effect_zh: "高级人格（具体效果需进一步解析）",
    activated_behaviors: [],
    activated_skills_zh: ["高级技能"]
  },
  zhanzhengshizhe: {
    name_zh: "战争使者",
    tier: 3,
    tier_zh: "3阶",
    effect_zh: "视野+3，对建筑伤害+100%",
    activated_behaviors: ["13gaojijiaozhunchengxu"],
    activated_skills_zh: ["高级校准程序（射程+1，重甲伤害+50%）"]
  }
};

// 蒙斯克战甲单位映射（基础单位 → 战甲单位）
const MENGSK_ZHANJIA_BASE = {
  "13buxiuzhezhanjia":    { base_id: "13buxiuzhe",    base_zh: "不朽者",   zhanjia_zh: "不朽者战甲" },
  "13chengjiezhezhanjia": { base_id: "13chengjiezhe", base_zh: "惩戒者",   zhanjia_zh: "惩戒者战甲" },
  "13chuanxinzhezhanjia": { base_id: "13chuanxinzhe", base_zh: "传信者",   zhanjia_zh: "传信者战甲" },
  "13puluobisizhanjia":   { base_id: "13puluobisi",   base_zh: "普罗比斯", zhanjia_zh: "普罗比斯战甲" },
  "13saodangzhezhanjia":  { base_id: "13saodangzhe",  base_zh: "扫荡者",   zhanjia_zh: "扫荡者战甲" },
  "13tansuozhezhanjia":   { base_id: "13tansuozhe",   base_zh: "探索者",   zhanjia_zh: "探索者战甲" },
  "13zhongjiezhezhanjia": { base_id: "13zhongjiezhe", base_zh: "终结者",   zhanjia_zh: "终结者战甲" },
  "13zhizhengzhezhanjia": { base_id: "13zhizhengzhe", base_zh: "执政者",   zhanjia_zh: "执政者战甲" }
};

// 形态后缀识别规则
const FORM_SUFFIXES = [
  { pattern: /zhanjia$/i, label: "战甲形态" },
  { pattern: /touying$/i, label: "投影形态" },
  { pattern: /canhai$/i, label: "残骸形态" },
  { pattern: /Burrowed$/i, label: "潜地形态" },
  { pattern: /Uprooted$/i, label: "拔起形态" },
  { pattern: /Phasing$/i, label: "相位形态" },
  { pattern: /Transport$/i, label: "运输形态" },
  { pattern: /Placement$/i, label: "放置物" },
  { pattern: /Weapon$/i, label: "投射物" },
  { pattern: /Missile$/i, label: "投射物" },
  { pattern: /Start$/i, label: "起始形态" }
];

function detectForm(id) {
  for (const { pattern, label } of FORM_SUFFIXES) {
    if (pattern.test(id)) return label;
  }
  return "基础形态";
}

// 加载 GameStrings.txt 提取 Unit/Name/<id>=<中文名>
function loadGameStrings(modDir) {
  const txtPath = join(modDir, "zhCN.SC2Data", "LocalizedData", "GameStrings.txt");
  if (!existsSync(txtPath)) return new Map();
  const text = readFileSync(txtPath, "utf8");
  const map = new Map();
  for (const line of text.split(/\r?\n/)) {
    if (!line || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq < 0) continue;
    const key = line.slice(0, eq);
    const val = line.slice(eq + 1);
    if (key.startsWith("Unit/Name/")) {
      const id = key.slice("Unit/Name/".length);
      map.set(id, val);
    }
  }
  return map;
}

// 从 UnitData.xml 提取每个单位的 LifeRegenRate 和 ShieldRegenRate
// 简化实现：按 CUnit 块扫描，提取 id 和紧随其后的 regen 字段
function loadRegenRates(modDir) {
  const unitDataPath = join(modDir, "Base.SC2Data", "GameData", "UnitData.xml");
  if (!existsSync(unitDataPath)) return new Map();
  const text = readFileSync(unitDataPath, "utf8");
  const map = new Map();
  // 按行扫描，遇到 <CUnit id="..." 开始一个新单位块，直到下一个 <CUnit 或 </Catalog>
  const lines = text.split(/\r?\n/);
  let currentId = null;
  let pendingLifeRegen = null;
  let pendingShieldRegen = null;
  const flush = () => {
    if (currentId && (pendingLifeRegen !== null || pendingShieldRegen !== null)) {
      map.set(currentId, {
        life_regen: pendingLifeRegen ?? 0,
        shields_regen: pendingShieldRegen ?? 0
      });
    }
    currentId = null;
    pendingLifeRegen = null;
    pendingShieldRegen = null;
  };
  for (const raw of lines) {
    const line = raw.trim();
    // 新单位块开始
    const startMatch = line.match(/^<CUnit\s+id="([^"]+)"/);
    if (startMatch) {
      flush();
      currentId = startMatch[1];
      continue;
    }
    if (line.startsWith("</Catalog>")) {
      flush();
      break;
    }
    if (currentId) {
      // 同一单位块内，提取 regen 字段
      const lifeMatch = line.match(/<LifeRegenRate\s+value="([^"]+)"\s*\/?>/);
      if (lifeMatch) {
        pendingLifeRegen = parseFloat(lifeMatch[1]) || 0;
      }
      const shieldMatch = line.match(/<ShieldRegenRate\s+value="([^"]+)"\s*\/?>/);
      if (shieldMatch) {
        pendingShieldRegen = parseFloat(shieldMatch[1]) || 0;
      }
      // 单位块结束（自闭合或显式关闭）
      if (line === "/>" || line === "</CUnit>") {
        flush();
      }
    }
  }
  flush();
  return map;
}

// 判断单位是否有"持续回盾"机制（Alenger3 风格）
// 规则：shields_max > 0 且 shields_regen >= 2（普通 SC2 护盾仅在脱战 2s 后回复，≥2 表示持续战斗中也回复）
function hasContinuousShieldRegen(unit, regenInfo) {
  if (!regenInfo) return false;
  return unit.shields_max > 0 && regenInfo.shields_regen >= 2;
}

// 判断单位是否有"持续回血"机制（Alenger6 风格）
// 规则：life_regen >= 2（普通单位 life_regen 通常 0~1）
function hasContinuousLifeRegen(regenInfo) {
  if (!regenInfo) return false;
  return regenInfo.life_regen >= 2;
}

// 计算阿巴瑟单位满生物质形态的数值
function computeBiomassMaxForm(unit) {
  const lifeMax = unit.life_max * BIOMASS_LIFE_MULT;
  const lifeArmor = unit.life_armor + BIOMASS_ARMOR_ADD;
  const shieldsMax = unit.shields_max; // 生物质不加护盾
  const weaponCount = unit.weapon_count || 0;
  const dpsGeneral = unit.dps_general * BIOMASS_ATTACK_SPEED_MULT + 4 * weaponCount;
  const dpsLight = unit.dps_light * BIOMASS_ATTACK_SPEED_MULT + 4 * weaponCount;
  const dpsArmored = unit.dps_armored * BIOMASS_ATTACK_SPEED_MULT + 4 * weaponCount;
  const dpsMassive = unit.dps_massive * BIOMASS_ATTACK_SPEED_MULT + 4 * weaponCount;
  const dpsAir = unit.dps_air * BIOMASS_ATTACK_SPEED_MULT + 4 * weaponCount;
  const dpsGround = unit.dps_ground * BIOMASS_ATTACK_SPEED_MULT + 4 * weaponCount;
  const maxRange = unit.max_range + BIOMASS_RANGE_ADD;
  const armorFactor = 1 + 0.05 * lifeArmor;
  const structurePenalty = unit.is_structure ? 0.6 : 1.0;
  const ehp = (lifeMax + shieldsMax) * armorFactor * structurePenalty;
  const rangeFactor = 1 + 0.05 * Math.max(0, maxRange - 3);
  return {
    life_max: lifeMax,
    life_armor: lifeArmor,
    shields_max: shieldsMax,
    dps_general: dpsGeneral,
    dps_light: dpsLight,
    dps_armored: dpsArmored,
    dps_massive: dpsMassive,
    dps_air: dpsAir,
    dps_ground: dpsGround,
    max_range: maxRange,
    ehp,
    range_factor: rangeFactor
  };
}

// 重新评分（基于现有公式）
function scoreUnit(unit, weights) {
  const C = unit.cost_normalized;
  if (!C || C <= 0) return { S: 0, primary_scenario: "unknown" };
  const ehp = unit.ehp;
  const rf = unit.range_factor;
  const sv = unit.skill_value || 0;
  const rm = unit.role_modifier || 1;
  const V_general = (unit.dps_general * ehp * rf + sv) * rm;
  const V_vs_light = (unit.dps_light * ehp * rf + sv) * rm;
  const V_vs_armored = (unit.dps_armored * ehp * rf + sv) * rm;
  const V_vs_air = (unit.dps_air * ehp * rf + sv) * rm;
  const V_vs_massive = (unit.dps_massive * ehp * rf + sv) * rm;
  const V_tank = (ehp * rf * 0.3 + sv * 0.5) * rm;
  const S_general = V_general / C;
  const S_vs_light = V_vs_light / C;
  const S_vs_armored = V_vs_armored / C;
  const S_vs_air = V_vs_air / C;
  const S_vs_massive = V_vs_massive / C;
  const S_tank = V_tank / C;
  const specializedMax = Math.max(S_vs_light, S_vs_armored, S_vs_air, S_vs_massive);
  const S = Math.max(S_general, specializedMax * 0.85, S_tank * 0.85);
  let primary = "generalist";
  let primaryVal = S_general;
  if (S_vs_light > primaryVal && S_vs_light * 0.85 >= S) primary = "anti_light";
  if (S_vs_armored > primaryVal && S_vs_armored * 0.85 >= S) primary = "anti_armored";
  if (S_vs_air > primaryVal && S_vs_air * 0.85 >= S) primary = "anti_air";
  if (S_vs_massive > primaryVal && S_vs_massive * 0.85 >= S) primary = "anti_massive";
  if (S_tank * 0.85 >= S) primary = "tank";
  return { S, primary_scenario: primary };
}

// 定位中文
const ROLE_ZH = {
  generalist: "通用",
  splash: "溅射",
  anti_light: "克轻甲",
  anti_armored: "克重甲",
  anti_air: "克空",
  anti_massive: "克巨型",
  tank: "肉盾"
};
const RACE_ZH = {
  Terr: "人族",
  Prot: "星灵",
  Zerg: "异虫",
  InfT: "感染人",
  PZrg: "异星",
  Unknown: "未知"
};

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

// 判断单位是否为建筑物
function isStructure(u) {
  if (u.is_structure) return true;
  // 兜底：常见建筑后缀
  if (/chongxue|fuhuachang|jinhuaqiang|zhuchao|duanlu|xingmen|jixietai|kongzhixinhe|yinglingdian|jinghuazheshuniu|jinghuazhehexin|cuidqufang|yingxionghexin|jianduihangbiao|chuansongmen|guangzipaotai|yazhita|hudunchongnengqi|jixieyanjiusuo|baowenchaoxue|paotai|ta/i.test(u.id)) {
    return true;
  }
  return false;
}

// 判断是否为投射物（应过滤）
function isProjectile(u) {
  return /Weapon$|Missile$|Projectile$|Dan$|Dan1$|Huangchong$|Huangchong1$|Huangchong2$/i.test(u.id)
    || /huangchong/i.test(u.id) && u.life_max < 50;
}

async function main() {
  console.log("[detailed] 加载数据...");
  const raw = await readJson("units-raw.json");
  const scored = await readJson("units-scored.json");
  const outliers = await readJson("outliers.json");
  const weights = await readJson("formula-weights.json");

  // 构建 scored 的 id → scored 映射
  const scoredMap = new Map();
  for (const u of scored.units) {
    scoredMap.set(`${u.commander}::${u.id}`, u);
  }

  // 加载每个指挥官的中文名映射和回复速率
  const nameMaps = new Map(); // commander -> Map<id, zhName>
  const regenMaps = new Map(); // commander -> Map<id, {life_regen, shields_regen}>
  for (const cmdr of Object.keys(raw.commanders)) {
    const modDir = join(MODS_ROOT, `${cmdr}.SC2Mod`);
    if (!existsSync(modDir)) {
      console.warn(`[detailed] mod 目录不存在: ${modDir}`);
      nameMaps.set(cmdr, new Map());
      regenMaps.set(cmdr, new Map());
      continue;
    }
    const m = loadGameStrings(modDir);
    nameMaps.set(cmdr, m);
    const r = loadRegenRates(modDir);
    regenMaps.set(cmdr, r);
    console.log(`[detailed] ${cmdr}: 加载 ${m.size} 条中文名, ${r.size} 条回复速率`);
  }

  // 按指挥官组装单位详情
  const allCmdrReports = [];
  for (const [cmdr, units] of Object.entries(raw.commanders)) {
    const nameMap = nameMaps.get(cmdr) || new Map();
    const regenMap = regenMaps.get(cmdr) || new Map();
    const unitsDetail = [];

    for (const u of units) {
      const s = scoredMap.get(`${cmdr}::${u.id}`) || {};
      const form = detectForm(u.id);
      const nameZh = nameMap.get(u.id) || "";
      const hasBiomass = (u.behavior_links || []).some((b) => b.includes("shengwuzhi"));
      const isZhanjia = /zhanjia$/i.test(u.id);
      const regen = regenMap.get(u.id) || { life_regen: 0, shields_regen: 0 };
      const hasShieldRegen = hasContinuousShieldRegen(u, regen);
      const hasLifeRegen = hasContinuousLifeRegen(regen);

      const detail = {
        id: u.id,
        name_zh: nameZh,
        form,
        commander: cmdr,
        race: u.race,
        race_zh: RACE_ZH[u.race] || u.race,
        is_structure: isStructure(u),
        is_hero: u.is_hero,
        is_worker: u.is_worker,
        is_air: u.is_air,
        is_projectile: isProjectile(u),
        is_zhanjia: isZhanjia,
        // 回复机制
        life_regen: regen.life_regen,
        shields_regen: regen.shields_regen,
        has_continuous_shield_regen: hasShieldRegen,
        has_continuous_life_regen: hasLifeRegen,
        // 白板数值
        baseline: {
          life_max: u.life_max,
          life_armor: u.life_armor,
          shields_max: u.shields_max,
          dps_general: u.dps_general,
          max_range: u.max_range,
          ehp: u.ehp,
          cost_normalized: u.cost_normalized,
          minerals: u.minerals,
          vespene: u.vespene,
          supply: u.supply,
          S: s.S || 0,
          primary_role: s.primary_role || "generalist",
          primary_role_zh: ROLE_ZH[s.primary_role] || "通用",
          z_internal: s.z_internal || 0,
          z_official: s.z_official || 0,
          is_outlier: false
        },
        forms: []
      };

      // 标记离群
      const myOutlier = outliers.outliers.find((o) => o.commander === cmdr && o.id === u.id);
      if (myOutlier) {
        detail.baseline.is_outlier = true;
        detail.baseline.outlier_direction = myOutlier.z_internal > 0 ? "偏强" : "偏弱";
      }

      // 阿巴瑟单位：计算满生物质形态
      if (hasBiomass && u.cost_normalized > 0 && u.life_max > 0) {
        const biomassForm = computeBiomassMaxForm(u);
        const scored2 = scoreUnit(
          {
            dps_general: biomassForm.dps_general,
            dps_light: biomassForm.dps_light,
            dps_armored: biomassForm.dps_armored,
            dps_air: biomassForm.dps_air,
            dps_massive: biomassForm.dps_massive,
            ehp: biomassForm.ehp,
            range_factor: biomassForm.range_factor,
            skill_value: u.skill_value,
            role_modifier: u.role_modifier,
            cost_normalized: u.cost_normalized
          },
          weights
        );
        detail.forms.push({
          form_type: "biomass_max",
          form_name: "满生物质（100 层）",
          life_max: biomassForm.life_max,
          life_armor: biomassForm.life_armor,
          shields_max: biomassForm.shields_max,
          dps_general: biomassForm.dps_general,
          max_range: biomassForm.max_range,
          ehp: biomassForm.ehp,
          S: scored2.S,
          primary_scenario: scored2.primary_scenario,
          primary_scenario_zh: ROLE_ZH[scored2.primary_scenario] || "通用",
          // 加成倍率
          life_mult: biomassForm.life_max / u.life_max,
          dps_mult: biomassForm.dps_general / (u.dps_general || 1),
          ehp_mult: biomassForm.ehp / (u.ehp || 1)
        });
      }

      // 蒙斯克战甲单位：列出所有人格形态（数据相同，技能不同）
      if (isZhanjia && MENGSK_ZHANJIA_BASE[u.id]) {
        const zjInfo = MENGSK_ZHANJIA_BASE[u.id];
        detail.zhanjia_info = {
          base_id: zjInfo.base_id,
          base_zh: zjInfo.base_zh,
          zhanjia_zh: zjInfo.zhanjia_zh,
          persona_forms: []
        };
        for (const [personaId, persona] of Object.entries(MENGSK_PERSONAS)) {
          // 检查战甲单位的 behavior_links 是否包含该人格激活的被动
          const unitBehaviors = u.behavior_links || [];
          const activated = persona.activated_behaviors.filter((b) => unitBehaviors.includes(b));
          detail.zhanjia_info.persona_forms.push({
            persona_id: personaId,
            persona_name_zh: persona.name_zh,
            tier: persona.tier,
            tier_zh: persona.tier_zh,
            persona_effect_zh: persona.effect_zh,
            activated_skills_zh: persona.activated_skills_zh,
            // 战甲单位本身的数值不变
            life_max: u.life_max,
            life_armor: u.life_armor,
            shields_max: u.shields_max,
            dps_general: u.dps_general,
            max_range: u.max_range,
            ehp: u.ehp,
            cost_normalized: u.cost_normalized,
            // 该人格是否激活此战甲的专属技能
            has_persona_skills: activated.length > 0 || persona.tier === 1 || persona.tier === 2 || persona.tier === 3
          });
        }
      }

      unitsDetail.push(detail);
    }

    // 按 form 分组排序：基础形态 → 战甲形态 → 其他
    const formOrder = {
      "基础形态": 0,
      "战甲形态": 1,
      "投影形态": 2,
      "潜地形态": 3,
      "拔起形态": 4,
      "相位形态": 5,
      "运输形态": 6,
      "起始形态": 7,
      "残骸形态": 8,
      "放置物": 9,
      "投射物": 10
    };
    unitsDetail.sort((a, b) => {
      const fa = formOrder[a.form] ?? 99;
      const fb = formOrder[b.form] ?? 99;
      if (fa !== fb) return fa - fb;
      // 同形态内按 S 降序
      return (b.baseline.S || 0) - (a.baseline.S || 0);
    });

    allCmdrReports.push({
      commander: cmdr,
      commander_zh: COMMANDER_NAMES_ZH[cmdr] || cmdr,
      unit_count: unitsDetail.length,
      units: unitsDetail
    });
  }

  // 按指挥官编号排序
  allCmdrReports.sort((a, b) => {
    const na = parseInt(a.commander.replace("Alenger", ""), 10);
    const nb = parseInt(b.commander.replace("Alenger", ""), 10);
    return na - nb;
  });

  // 写结构化 JSON
  console.log("[detailed] 写入 detailed-units.json...");
  await mkdir(OUTPUT_DIR, { recursive: true });
  await writeFile(
    join(OUTPUT_DIR, "detailed-units.json"),
    JSON.stringify(
      {
        schema_version: 2,
        generated_at: new Date().toISOString(),
        commanders: allCmdrReports
      },
      null,
      2
    ),
    "utf8"
  );

  // 生成 Markdown
  console.log("[detailed] 生成 detailed-report.md...");
  const md = generateMarkdown(allCmdrReports, weights);
  await writeFile(join(OUTPUT_DIR, "detailed-report.md"), md, "utf8");

  console.log("[detailed] === 完成 ===");
  console.log(`[detailed] 报告目录: ${OUTPUT_DIR}`);
  console.log(`[detailed] 指挥官数: ${allCmdrReports.length}`);
  for (const c of allCmdrReports) {
    const biomassUnits = c.units.filter((u) => u.forms.length > 0).length;
    const zhanjiaUnits = c.units.filter((u) => u.is_zhanjia).length;
    console.log(`  ${c.commander}: ${c.unit_count} 单位（其中 ${biomassUnits} 个有满加成形态，${zhanjiaUnits} 个战甲形态）`);
  }
}

function generateMarkdown(cmdrReports, weights) {
  const lines = [];
  lines.push(`# SC2 起义指挥官单位平衡详细报告（中文）`);
  lines.push("");
  lines.push(`**生成时间**：${new Date().toISOString()}`);
  lines.push(`**评估公式**：v4（DPS × EHP × range_factor + skill_value）× role_modifier / cost_normalized`);
  lines.push(`**形态识别**：基础形态 / 战甲形态（蒙斯克）/ 满生物质（阿巴瑟）/ 潜地形态等`);
  lines.push(`**报告范围**：所有起义指挥官的全部单位与建筑，含中文名、ID、形态、白板数据、满加成形态`);
  lines.push("");
  lines.push("---");
  lines.push("");
  lines.push("## 0. 形态说明");
  lines.push("");
  lines.push("### 0.1 阿巴瑟生物质机制（Alenger6）");
  lines.push("");
  lines.push("阿巴瑟单位通过击杀、挨打、自动获取生物质，每层提供以下加成（基于 BehaviorData.xml 解析）：");
  lines.push("");
  lines.push("| 加成项 | 每层 | 满层（100） |");
  lines.push("|--------|------|-------------|");
  lines.push(`| 生命值 | +3% Max Life | × ${BIOMASS_LIFE_MULT} |`);
  lines.push(`| 护甲 | +0.04 | + ${BIOMASS_ARMOR_ADD} |`);
  lines.push(`| 远程武器伤害（每武器） | +0.04 unscaled | + ${BIOMASS_DAMAGE_ADD_PER_WEAPON} |`);
  lines.push(`| 远程武器射程 | +0.04 | + ${BIOMASS_RANGE_ADD} |`);
  lines.push(`| 攻击速度（25/50/75/100 层叠加） | 1.25 × 1.2 × 1.16 × 1.1428 | × ${BIOMASS_ATTACK_SPEED_MULT} |`);
  lines.push("");
  lines.push("**生物质获取机制**（关键）：");
  lines.push("- `6shengwuzhidarenshanghaixiangying`（挨打触发）：受到伤害时获取生物质，冷却 1 秒");
  lines.push("- `6shengwuzhiaidashanghaixiangying`（造成伤害触发）：造成伤害时获取生物质，冷却 1 秒");
  lines.push("- `6shengwuzhihuoquSearch`（搜索获取）：通过搜索范围自动获取生物质");
  lines.push("- `6shengwuzhihuoquPersistent`（持续获取）：被动持续获取生物质");
  lines.push("");
  lines.push("**结论**：生物质获取极其容易（挨打+造成伤害都触发，冷却仅 1 秒），实战中满 100 层是常态而非特例。");
  lines.push("");
  lines.push("**注**：生物质加成仅适用于单位本身，造价不变。满加成形态的 S 值显著高于白板。");
  lines.push("");
  lines.push("### 0.2 Alenger3 持续护盾回复机制");
  lines.push("");
  lines.push("Alenger3 单位普遍具有持续护盾回复（`ShieldRegenRate` ≥ 2），且大部分单位回复速率极高（10~150/秒）：");
  lines.push("");
  lines.push("| 回盾速率 | 等级 | 实战效果 |");
  lines.push("|----------|------|----------|");
  lines.push("| 2-4/秒 | 普通 | 缓慢回盾，约 30 秒回满 |");
  lines.push("| 4-10/秒 | 高 | 战斗中持续回盾 |");
  lines.push("| 10-30/秒 | 极高 | 几乎不掉盾 |");
  lines.push("| ≥30/秒 | 超标 | 等效于全程无敌 |");
  lines.push("");
  lines.push("**对比标准 SC2**：普通单位的护盾仅在脱战 2 秒后回复，速率约 2/秒。Alenger3 的回盾速率远超标准值。");
  lines.push("");
  lines.push("**结论**：Alenger3 的实际有效血量 = EHP × (1 + 回盾速率 × 战斗时长 / 护盾值)，在持续战斗中远超纸面 EHP。");
  lines.push("");
  lines.push("### 0.3 蒙斯克战甲机制（Alenger13）");
  lines.push("");
  lines.push("蒙斯克通过 `13yingxionghexin`（英雄核心）使用 `13zheyuebianxing5`（折跃变形）召唤战甲高阶形态。");
  lines.push("**战甲单位本身的数据（血量/护甲/造价）固定不变，但根据英雄核心当前下载的人格激活不同的被动技能，导致实际战斗效果完全不同。**");
  lines.push("");
  lines.push("#### 0.3.1 英雄核心人格分级（1阶/2阶/3阶）");
  lines.push("");
  lines.push("| 人格 ID | 中文名 | 阶级 | 效果 |");
  lines.push("|---------|--------|------|------|");
  for (const [pid, p] of Object.entries(MENGSK_PERSONAS)) {
    lines.push(`| ${pid} | ${p.name_zh} | ${p.tier_zh} | ${p.effect_zh} |`);
  }
  lines.push("");
  lines.push("#### 0.3.2 战甲单位列表");
  lines.push("");
  lines.push("| 基础单位 | 战甲形态 | 召唤来源 |");
  lines.push("|----------|----------|----------|");
  for (const [zjId, info] of Object.entries(MENGSK_ZHANJIA_BASE)) {
    lines.push(`| ${info.base_id} ${info.base_zh} | ${zjId} ${info.zhanjia_zh} | 英雄核心折跃变形 |`);
  }
  lines.push("");
  lines.push("**注**：同一战甲在不同人格下数据相同但技能完全不同。例如：");
  lines.push("- 不朽者战甲在 **1阶卡尔达利斯** 下：激活无畏狂热者（首次攻击触发）+ 狂怒（攻速 ×3）");
  lines.push("- 不朽者战甲在 **2阶塔尔达林** 下：激活永恒压缩系统 + 英雄不朽");
  lines.push("- 不朽者战甲在 **3阶战争使者** 下：激活高级校准程序（射程+1，重甲伤害+50%）");
  lines.push("");
  lines.push("### 0.4 通用形态后缀");
  lines.push("");
  lines.push("| 后缀 | 形态 | 说明 |");
  lines.push("|------|------|------|");
  lines.push("| Burrowed | 潜地形态 | 潜地后通常 DPS=0，仅有被动加成 |");
  lines.push("| Uprooted | 拔起形态 | 爬虫爬行状态 |");
  lines.push("| Phasing | 相位形态 | 棱镜相位模式 |");
  lines.push("| Transport | 运输形态 | 棱镜运输模式 |");
  lines.push("| Placement | 放置物 | 建筑放置预览 |");
  lines.push("| Weapon/Missile | 投射物 | 飞弹单位（不计入主战） |");
  lines.push("");
  lines.push("---");
  lines.push("");

  // 按指挥官输出
  for (const cmdr of cmdrReports) {
    lines.push(`## ${cmdr.commander} — ${cmdr.commander_zh}`);
    lines.push("");
    lines.push(`**单位总数**：${cmdr.unit_count}`);
    lines.push("");

    // 按形态分组统计
    const formGroups = {};
    for (const u of cmdr.units) {
      if (!formGroups[u.form]) formGroups[u.form] = [];
      formGroups[u.form].push(u);
    }
    lines.push("**形态分布**：");
    lines.push("");
    lines.push("| 形态 | 数量 |");
    lines.push("|------|------|");
    for (const [form, arr] of Object.entries(formGroups)) {
      lines.push(`| ${form} | ${arr.length} |`);
    }
    lines.push("");

    // 按类型分组：英雄单位、建筑、普通单位、投射物
    const heroes = cmdr.units.filter((u) => u.is_hero && !u.is_zhanjia);
    const zhanjiaUnits = cmdr.units.filter((u) => u.is_zhanjia);
    const structures = cmdr.units.filter((u) => u.is_structure && !u.is_hero);
    const normalUnits = cmdr.units.filter((u) => !u.is_hero && !u.is_structure && !u.is_zhanjia && !u.is_projectile);
    const projectiles = cmdr.units.filter((u) => u.is_projectile);

    // 主表：所有主战单位（含英雄、战甲、普通单位）
    lines.push("### 单位详情（全部单位）");
    lines.push("");
    lines.push("| 中文名 | ID | 形态 | 种族 | 定位 | 血量 | 护甲 | 护盾 | 回血/秒 | 回盾/秒 | EHP | DPS | 射程 | 造价(矿/气/补) | S | z_internal | 离群 | 满加成 S |");
    lines.push("|--------|-----|------|------|------|------|------|------|---------|---------|-----|-----|------|----------------|---|------------|------|----------|");
    for (const u of cmdr.units) {
      const b = u.baseline;
      const biomassS = u.forms.find((f) => f.form_name.includes("满生物质"));
      const outlierMark = b.is_outlier ? `${b.outlier_direction}` : "";
      const biomassMark = biomassS ? fmt(biomassS.S, 2) : "—";
      const costStr = `${b.minerals||0}/${b.vespene||0}/${b.supply||0}`;
      const heroMark = u.is_hero ? "★" : "";
      const zhanjiaMark = u.is_zhanjia ? "⚔" : "";
      const structMark = u.is_structure ? "□" : "";
      // 回复速率：仅显示有意义的值
      const lifeRegenStr = u.life_regen > 0 ? fmt(u.life_regen, 1) : "—";
      const shieldRegenStr = u.shields_regen > 0 ? fmt(u.shields_regen, 1) : "—";
      // 持续回复标记（Alenger3 护盾、Alenger6 血量）
      const regenFlag = u.has_continuous_shield_regen || u.has_continuous_life_regen ? "⚡" : "";
      lines.push(
        `| ${heroMark}${zhanjiaMark}${structMark}${regenFlag}${u.name_zh || "(无名)"} | ${u.id} | ${u.form} | ${u.race_zh} | ${b.primary_role_zh} | ${fmt(b.life_max, 0)} | ${fmt(b.life_armor, 1)} | ${fmt(b.shields_max, 0)} | ${lifeRegenStr} | ${shieldRegenStr} | ${fmt(b.ehp, 0)} | ${fmt(b.dps_general, 1)} | ${fmt(b.max_range, 1)} | ${costStr} | ${fmt(b.S, 2)} | ${fmt(b.z_internal, 2)} | ${outlierMark} | ${biomassMark} |`
      );
    }
    lines.push("");
    lines.push("> 标记说明：★ 英雄单位、⚔ 战甲形态、□ 建筑、⚡ 持续回复（战斗中仍回复）");
    lines.push("");

    // 持续回复统计章节
    const shieldRegenUnits = cmdr.units.filter((u) => u.has_continuous_shield_regen);
    const lifeRegenUnits = cmdr.units.filter((u) => u.has_continuous_life_regen);
    if (shieldRegenUnits.length > 0 || lifeRegenUnits.length > 0) {
      lines.push("### 持续回复机制（战斗中仍生效）");
      lines.push("");
      lines.push("**说明**：标准 SC2 中护盾仅脱战 2 秒后回复，生命值基本不回复。以下单位具有持续回复能力（战斗中仍回复），实际有效血量远超 EHP 数值。");
      lines.push("");

      if (shieldRegenUnits.length > 0) {
        lines.push("#### 持续回盾单位（Alenger3 风格）");
        lines.push("");
        lines.push("| 中文名 | ID | 护盾 | 回盾/秒 | 满盾时间 | 战斗中持续 | 说明 |");
        lines.push("|--------|-----|------|---------|----------|-----------|------|");
        for (const u of shieldRegenUnits) {
          const fullShieldTime = u.shields_regen > 0 ? (u.baseline.shields_max / u.shields_regen).toFixed(1) : "N/A";
          const note = u.shields_regen >= 10 ? "极高（几乎不掉盾）" : u.shields_regen >= 4 ? "高（战斗中持续回盾）" : "中（缓慢回盾）";
          lines.push(`| ${u.name_zh || "(无名)"} | ${u.id} | ${fmt(u.baseline.shields_max, 0)} | ${fmt(u.shields_regen, 1)} | ${fullShieldTime}s | 是 | ${note} |`);
        }
        lines.push("");
        lines.push(`**小计**：${shieldRegenUnits.length} 个单位具有持续回盾能力，占 ${cmdr.unit_count} 个单位的 ${(shieldRegenUnits.length / cmdr.unit_count * 100).toFixed(1)}%`);
        lines.push("");
      }

      if (lifeRegenUnits.length > 0) {
        lines.push("#### 持续回血单位（Alenger6 风格）");
        lines.push("");
        lines.push("| 中文名 | ID | 血量 | 回血/秒 | 满血时间 | 战斗中持续 | 说明 |");
        lines.push("|--------|-----|------|---------|----------|-----------|------|");
        for (const u of lifeRegenUnits) {
          const fullLifeTime = u.life_regen > 0 ? (u.baseline.life_max / u.life_regen).toFixed(1) : "N/A";
          const note = u.life_regen >= 4 ? "极高（极快回血）" : u.life_regen >= 2 ? "高（持续回血）" : "中（缓慢回血）";
          lines.push(`| ${u.name_zh || "(无名)"} | ${u.id} | ${fmt(u.baseline.life_max, 0)} | ${fmt(u.life_regen, 1)} | ${fullLifeTime}s | 是 | ${note} |`);
        }
        lines.push("");
        lines.push(`**小计**：${lifeRegenUnits.length} 个单位具有持续回血能力，占 ${cmdr.unit_count} 个单位的 ${(lifeRegenUnits.length / cmdr.unit_count * 100).toFixed(1)}%`);
        lines.push("");
      }
    }

    // 阿巴瑟特殊：满生物质形态对比
    const biomassUnits = cmdr.units.filter((u) => u.forms.length > 0);
    if (biomassUnits.length > 0) {
      lines.push("### 满生物质（100 层）形态对比 — 白板 vs 满加成");
      lines.push("");
      lines.push("| 中文名 | ID | 形态 | 血量 | 血量倍率 | 护甲 | DPS | DPS倍率 | EHP | EHP倍率 | 射程 | S（白板） | S（满生物质） | 增益倍率 |");
      lines.push("|--------|-----|------|------|----------|------|-----|---------|-----|---------|------|-----------|----------------|----------|");
      for (const u of biomassUnits) {
        const b = u.baseline;
        const f = u.forms[0];
        lines.push(
          `| ${u.name_zh || "(无名)"} | ${u.id} | ${f.form_name} | ${fmt(f.life_max, 0)} | ×${fmt(f.life_mult, 2)} | ${fmt(f.life_armor, 1)} | ${fmt(f.dps_general, 1)} | ×${fmt(f.dps_mult, 2)} | ${fmt(f.ehp, 0)} | ×${fmt(f.ehp_mult, 2)} | ${fmt(f.max_range, 1)} | ${fmt(b.S, 2)} | ${fmt(f.S, 2)} | ×${fmt(f.S / (b.S || 1), 2)} |`
        );
      }
      lines.push("");
      lines.push("**结论**：阿巴瑟单位白板数值偏低（S 值低），但满生物质（100 层）后血量 ×4、DPS ×2、护甲 +4，实际强度远超白板评分。平衡调整时应参考满生物质 S 值。");
      lines.push("");
    }

    // 蒙斯克战甲：人格形态对比
    if (zhanjiaUnits.length > 0) {
      lines.push("### 战甲形态 — 人格分级对比（1阶/2阶/3阶）");
      lines.push("");
      lines.push("战甲单位本身数据固定，但根据英雄核心人格激活不同的被动技能：");
      lines.push("");
      lines.push("#### 战甲单位基础数据");
      lines.push("");
      lines.push("| 战甲 | 中文名 | 血量 | 护甲 | 护盾 | DPS | 射程 | 造价 | S |");
      lines.push("|------|--------|------|------|------|-----|------|------|---|");
      for (const u of zhanjiaUnits) {
        const b = u.baseline;
        const zjInfo = u.zhanjia_info;
        const zjZh = zjInfo ? zjInfo.zhanjia_zh : (u.name_zh || "(无名)");
        lines.push(
          `| ${u.id} | ${zjZh} | ${fmt(b.life_max, 0)} | ${fmt(b.life_armor, 1)} | ${fmt(b.shields_max, 0)} | ${fmt(b.dps_general, 1)} | ${fmt(b.max_range, 1)} | ${fmt(b.cost_normalized, 0)} | ${fmt(b.S, 2)} |`
        );
      }
      lines.push("");
      lines.push("#### 战甲单位在不同人格下的技能激活");
      lines.push("");
      lines.push("| 战甲 | 1阶人格 | 1阶激活技能 | 2阶人格 | 2阶激活技能 | 3阶人格 | 3阶激活技能 |");
      lines.push("|------|---------|-----------|---------|-----------|---------|-----------|");
      for (const u of zhanjiaUnits) {
        if (!u.zhanjia_info) continue;
        const forms = u.zhanjia_info.persona_forms;
        const tier1 = forms.filter((f) => f.tier === 1);
        const tier2 = forms.filter((f) => f.tier === 2);
        const tier3 = forms.filter((f) => f.tier === 3);
        const t1Names = tier1.map((f) => f.persona_name_zh).join(" / ");
        const t1Skills = tier1.map((f) => f.activated_skills_zh.join("+")).join(" / ");
        const t2Names = tier2.map((f) => f.persona_name_zh).join(" / ");
        const t2Skills = tier2.map((f) => f.activated_skills_zh.join("+")).join(" / ");
        const t3Names = tier3.map((f) => f.persona_name_zh).join(" / ");
        const t3Skills = tier3.map((f) => f.activated_skills_zh.join("+")).join(" / ");
        const zjZh = u.zhanjia_info.zhanjia_zh;
        lines.push(`| ${zjZh} | ${t1Names} | ${t1Skills} | ${t2Names} | ${t2Skills} | ${t3Names} | ${t3Skills} |`);
      }
      lines.push("");
      lines.push("**结论**：同一战甲在不同人格下数据相同但技能完全不同。例如：");
      lines.push("- 不朽者战甲在 1阶卡尔达利斯下：攻速 ×3 + 无畏狂热者");
      lines.push("- 不朽者战甲在 2阶塔尔达林下：永恒压缩系统 + 英雄不朽");
      lines.push("- 不朽者战甲在 3阶战争使者下：高级校准程序（射程+1，重甲伤害+50%）");
      lines.push("- 平衡调整时需结合人格分级综合考虑，不能仅按白板数据评判");
      lines.push("");
    }

    // 离群单位详情
    const outlierUnits = cmdr.units.filter((u) => u.baseline.is_outlier);
    if (outlierUnits.length > 0) {
      lines.push("### 离群单位详情");
      lines.push("");
      lines.push("| 中文名 | ID | 形态 | 定位 | S | 造价 | z_internal | z_official | 方向 |");
      lines.push("|--------|-----|------|------|---|------|------------|------------|------|");
      for (const u of outlierUnits) {
        const b = u.baseline;
        lines.push(
          `| ${u.name_zh || "(无名)"} | ${u.id} | ${u.form} | ${b.primary_role_zh} | ${fmt(b.S, 2)} | ${fmt(b.cost_normalized, 0)} | ${fmt(b.z_internal, 2)} | ${fmt(b.z_official, 2)} | ${b.outlier_direction} |`
        );
      }
      lines.push("");
    }

    // 建筑物列表
    if (structures.length > 0) {
      lines.push("### 建筑清单");
      lines.push("");
      lines.push("| 中文名 | ID | 血量 | 护甲 | 护盾 | 造价(矿/气) | 类型 |");
      lines.push("|--------|-----|------|------|------|------------|------|");
      for (const u of structures) {
        const b = u.baseline;
        lines.push(
          `| ${u.name_zh || "(无名)"} | ${u.id} | ${fmt(b.life_max, 0)} | ${fmt(b.life_armor, 1)} | ${fmt(b.shields_max, 0)} | ${b.minerals||0}/${b.vespene||0} | 建筑 |`
        );
      }
      lines.push("");
    }

    // 投射物/召唤物列表
    if (projectiles.length > 0) {
      lines.push("### 投射物/召唤物（不计入主战评估）");
      lines.push("");
      lines.push("| 中文名 | ID | 血量 | DPS | 射程 |");
      lines.push("|--------|-----|------|-----|------|");
      for (const u of projectiles) {
        const b = u.baseline;
        lines.push(`| ${u.name_zh || "(无名)"} | ${u.id} | ${fmt(b.life_max, 0)} | ${fmt(b.dps_general, 1)} | ${fmt(b.max_range, 1)} |`);
      }
      lines.push("");
    }

    lines.push("---");
    lines.push("");
  }

  // 全局总结
  lines.push("## 总结");
  lines.push("");
  const totalUnits = cmdrReports.reduce((s, c) => s + c.unit_count, 0);
  const totalBiomass = cmdrReports.reduce((s, c) => s + c.units.filter((u) => u.forms.length > 0).length, 0);
  const totalZhanjia = cmdrReports.reduce((s, c) => s + c.units.filter((u) => u.is_zhanjia).length, 0);
  lines.push(`- 总单位数：**${totalUnits}**`);
  lines.push(`- 含满生物质形态单位：**${totalBiomass}**（阿巴瑟）`);
  lines.push(`- 含战甲形态单位：**${totalZhanjia}**（蒙斯克）`);
  lines.push(`- 指挥官数：${cmdrReports.length}`);
  lines.push("");
  lines.push("### 关键观察");
  lines.push("");
  lines.push("- **Alenger6（阿巴瑟）**：单位白板数值偏低，但满生物质（100 层）后血量 ×4、DPS ×2、护甲 +4、射程 +4，实际强度远超白板评分（S 值增长 8~85 倍）");
  lines.push("- **Alenger13（蒙斯克）**：通过英雄核心召唤战甲形态，战甲单位本身数据固定但根据人格（1阶/2阶/3阶）激活不同被动技能");
  lines.push("  - 1阶人格（卡尔达利斯、提拉特）：基础战斗增强（攻速 ×3、伤害减半等）");
  lines.push("  - 2阶人格（科罗拉里昂、摩约、塔尔达林）：场景伤害加成（法术/对空/对地翻倍）");
  lines.push("  - 3阶人格（战争使者、卡拉斯）：高级技能（射程+1、对建筑伤害翻倍等）");
  lines.push("- **潜地/拔起形态**：潜地后 DPS 通常归零，仅作被动加成；拔起形态为爬虫爬行状态");
  lines.push("- **投射物单位**：飞弹/武器单位应被过滤，不计入主战单位评估");
  lines.push("");
  lines.push("### 调整建议");
  lines.push("");
  lines.push("- 对阿巴瑟单位：白板 S 值低估实际强度，建议参考满生物质 S 值做平衡调整（满加成 S 值约为白板的 8~85 倍）");
  lines.push("- 对蒙斯克战甲单位：需结合人格分级综合评估，不能仅按白板数据评判");
  lines.push("  - 1阶人格战甲：纯战斗增强，适合正面交锋");
  lines.push("  - 2阶人格战甲：场景特化，需根据敌方组成选择");
  lines.push("  - 3阶人格战甲：高级技能，全方位强化");
  lines.push("- 对离群单位：参考 patch-suggestions.json 的建议造价调整");
  lines.push("");

  return lines.join("\n");
}

main().catch((err) => {
  console.error("[detailed] FATAL:", err);
  console.error(err.stack);
  process.exit(1);
});
