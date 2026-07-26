// src/official-extract.mjs
// 原版 18 位合作指挥官单位提取（完整版 v2）
//
// 数据源：
//   1. sc2-porting-workspace/reference/sc2mapster/SC2GameData/mods/starcoop/starcoop.sc2mod
//      （合作 mod 共享数据，1741 个 CUnit，含 10 个 Faction 标签覆盖 11 位指挥官）
//   2. arcturusmengsk.sc2mod（蒙斯克专属数据，64 个 CUnit）
//   3. egonstetmann.sc2mod（斯特曼专属数据，85 个 CUnit，含 Mecha faction 83 个）
//
// 分类规则（两层）：
//   1. 优先：EditorCategories 的 ObjectFamily:Faction<X> 标签
//      - Raider → Raynor（雷诺）
//      - Evolved → Kerrigan（凯瑞甘，含 HotS/Kerrigan 单位）
//      - Primal → Dehaka（德哈卡）
//      - Infested → Stukov（斯图科夫）
//      - CovertOps → Nova（诺娃）
//      - Purifier → Fenix（菲尼克斯，注意不是凯拉克斯）
//      - Nerazim → Vorazun（沃拉尊）
//      - Taldarim → Alarak（阿拉纳克）
//      - Khalai → Artanis（阿塔尼斯）
//      - Marauder → Horner（霍纳与汉，含 HH* 单位）
//      - Mecha → Stetmann（斯特曼，在 stetmann mod 中）
//   2. 回退：ID 前缀匹配（用于 Karax/Zagara/Swann/Mengsk/Tychus/Zeratul/Abathur）
//      - Karax: Karax*/PurifierCellBlock*
//      - Zagara: Zagara*/Nydus*/ScourgeMP
//      - Swann: Swann*/Diamondback*/Hercules*/Vulture*
//      - Mengsk: Mengsk*/RoyalGuard*/Earthwatch*
//      - Tychus: Tychus*/Outlaw*
//      - Zeratul: Zeratul*/Void*/Shadow*
//      - Abathur: Abathur*/Biomass*/Locust*/Brutalisk*

import { readFile, writeFile, mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { parseCatalogXml, loadCatalogFiles } from "./xml-parser.mjs";
import { resolveAll } from "./parent-resolver.mjs";
import { extractUnitMetrics } from "./metrics.mjs";
import { scoreUnit, computeGroupStatistics } from "./formula.mjs";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const balanceRoot = resolve(scriptDir, "..");
const workspaceRoot = resolve(balanceRoot, "..", ".."); // sc2-porting-workspace/
const OUTPUT_DIR = resolve(workspaceRoot, "artifacts", "balance", "2026-07-26");

const CATALOG_FILES = ["UnitData.xml", "WeaponData.xml", "EffectData.xml", "AbilData.xml", "BehaviorData.xml"];

// 基础游戏 mod（用于 parent 解析，提供 Firebat/Diamondback/Goliath/Medic 等基础单位数据）
const BASE_GAME_MODS = [
  {
    id: "liberty",
    path: "reference/sc2mapster/SC2GameData/mods/liberty.sc2mod/base.sc2data/GameData"
  },
  {
    id: "swarm",
    path: "reference/sc2mapster/SC2GameData/mods/swarm.sc2mod/base.sc2data/GameData"
  },
  {
    id: "void",
    path: "reference/sc2mapster/SC2GameData/mods/void.sc2mod/base.sc2data/GameData"
  },
  {
    id: "libertymulti",
    path: "reference/sc2mapster/SC2GameData/mods/libertymulti.sc2mod/base.sc2data/GameData"
  },
  {
    id: "swarmmulti",
    path: "reference/sc2mapster/SC2GameData/mods/swarmmulti.sc2mod/base.sc2data/GameData"
  },
  {
    id: "voidmulti",
    path: "reference/sc2mapster/SC2GameData/mods/voidmulti.sc2mod/base.sc2data/GameData"
  }
];

// 合作 mod 列表（共享 + 指挥官专属）
const OFFICIAL_MODS = [
  {
    id: "starcoop_shared",
    path: "reference/sc2mapster/SC2GameData/mods/starcoop/starcoop.sc2mod/base.sc2data/GameData"
  },
  {
    id: "mengsk",
    path: "reference/sc2mapster/SC2GameData/mods/starcoop/commanders/arcturusmengsk.sc2mod/base.sc2data/GameData"
  },
  {
    id: "stetmann",
    path: "reference/sc2mapster/SC2GameData/mods/starcoop/commanders/egonstetmann.sc2mod/base.sc2data/GameData"
  }
];

// Faction → Commander 映射（已修正，基于实际单位 ID 验证）
const FACTION_TO_COMMANDER = {
  Raider:    "Raynor",     // 雷诺（Diamondback/Firebat/Goliath/Medic 等）
  Evolved:   "Kerrigan",   // 凯瑞甘（HotS/Kerrigan 前缀单位）
  Primal:    "Dehaka",     // 德哈卡
  Infested:  "Stukov",     // 斯图科夫
  CovertOps: "Nova",       // 诺娃
  Purifier:  "Fenix",      // 菲尼克斯（FenixTalis/FenixProbius 等）
  Nerazim:   "Vorazun",    // 沃拉尊
  Taldarim:  "Alarak",     // 阿拉纳克
  Khalai:    "Artanis",    // 阿塔尼斯
  Marauder:  "Horner",     // 霍纳与汉（HH* 单位）
  Mecha:     "Stetmann"    // 斯特曼
};

// ID 前缀 → Commander 映射（用于无 Faction 标签的指挥官）
const PREFIX_TO_COMMANDER = {
  Karax:    ["Karax"],
  Zagara:   ["Zagara", "Nydus", "ScourgeMP", "BileLauncher", "AberrationZ"],
  Swann:    ["Swann", "Diamondback", "Hercules", "VultureMP", "BattleRaptor"],
  Mengsk:   ["Mengsk", "RoyalGuard", "Earthwatch", "TrooperMengsk"],
  Tychus:   ["Tychus", "Outlaw"],
  Zeratul:  ["Zeratul", "VoidRay", "VoidSeeker", "VoidMP", "VoidRift", "VoidPylon", "ShadowArchon", "ShadowBattlecruiser", "ShadowShield"],
  Abathur:  ["Abathur", "Biomass", "Locust", "Brutalisk", "ToxicNest", "LeviathanAbathur"]
};

// ID 后缀 → Commander 映射（用于 Mengsk 的命名风格：<BaseUnit>Mengsk，如 BattlecruiserMengsk、TrooperMengsk）
// 注意：必须先检查后缀，避免被前缀匹配误判（例如 "MengskFirebat" 应归 Mengsk，而非 "Firebat" 误归其它）
const SUFFIX_TO_COMMANDER = {
  Mengsk: "Mengsk"  // BattlecruiserMengsk / TrooperMengsk / MarauderMengsk / ArmoryMengsk / ...
};

// 指挥官中文名 + 种族
const COMMANDER_INFO = {
  Raynor:   { zh: "雷诺",       race: "Terr" },
  Kerrigan: { zh: "凯瑞甘",     race: "Zerg" },
  Artanis:  { zh: "阿塔尼斯",   race: "Prot" },
  Swann:    { zh: "斯旺",       race: "Terr" },
  Zagara:   { zh: "扎加拉",     race: "Zerg" },
  Vorazun:  { zh: "沃拉尊",     race: "Prot" },
  Karax:    { zh: "凯拉克斯",   race: "Prot" },
  Alarak:   { zh: "阿拉纳克",   race: "Prot" },
  Nova:     { zh: "诺娃",       race: "Terr" },
  Stukov:   { zh: "斯图科夫",   race: "Zerg" },
  Dehaka:   { zh: "德哈卡",     race: "Zerg" },
  Fenix:    { zh: "菲尼克斯",   race: "Prot" },
  Mengsk:   { zh: "蒙斯克",     race: "Terr" },
  Stetmann: { zh: "斯特曼",     race: "Terr" },
  Tychus:   { zh: "泰凯斯",     race: "Terr" },
  Zeratul:  { zh: "泽拉图",     race: "Prot" },
  Horner:   { zh: "霍纳与汉",   race: "Terr" },
  Abathur:  { zh: "阿巴瑟",     race: "Zerg" }
};

// 辅助 ID 后缀过滤（与起义指挥官相同）
const AUXILIARY_SUFFIXES = ["Placement", "Weapon", "Search", "Damage", "Missile", "Effect", "Persistent", "Apply", "Buff", "Model", "Beam", "Sound", "Actor"];

function isAuxiliaryId(id) {
  for (const suffix of AUXILIARY_SUFFIXES) {
    if (id.includes(suffix)) return true;
  }
  return false;
}

function shouldSkipUnit(unit) {
  if (!unit.life_max || unit.life_max <= 0) return true;
  if (unit.life_max > 100000) return true;
  if (unit.minerals === 0 && unit.vespene === 0) return true;
  return false;
}

// 根据单位 ID 和 EditorCategories 判断属于哪个原版指挥官
function classifyCommander(unitId, entry) {
  // 0. 优先：ID 后缀匹配（处理 Mengsk 命名风格 <BaseUnit>Mengsk）
  // 注意：必须在前缀匹配之前，否则 "MengskFirebat" 会先匹配 "Mengsk" 前缀
  // 但 "MengskFirebat" 在 starcoop_shared 中只是 patching entry（无 LifeMax），会被 shouldSkipUnit 过滤
  // 而真正的数据在 mengsk mod 中以 <BaseUnit>Mengsk 形式存在
  for (const [suffix, commander] of Object.entries(SUFFIX_TO_COMMANDER)) {
    // 严格后缀匹配：<BaseUnit><Suffix>，且 Suffix 前一个字符非 Suffix 自身首字符（防止 "MengskMengsk"）
    if (unitId.endsWith(suffix) && unitId.length > suffix.length) {
      const prevChar = unitId[unitId.length - suffix.length - 1];
      // 后缀前必须是字母/数字（避免匹配到 "MenMengskGsk" 这种异常）
      if (/[A-Za-z0-9]/.test(prevChar)) {
        return commander;
      }
    }
  }
  // 1. 从 EditorCategories 提取 Faction
  if (entry && entry.fields && entry.fields.EditorCategories) {
    const ec = entry.fields.EditorCategories;
    const factionMatch = ec.match(/ObjectFamily:Faction(\w+)/);
    if (factionMatch) {
      const faction = factionMatch[1];
      if (FACTION_TO_COMMANDER[faction]) {
        return FACTION_TO_COMMANDER[faction];
      }
    }
  }
  // 2. 回退：ID 前缀匹配
  for (const [commander, prefixes] of Object.entries(PREFIX_TO_COMMANDER)) {
    for (const prefix of prefixes) {
      if (unitId === prefix) return commander;
      if (unitId.startsWith(prefix) && unitId.length > prefix.length) {
        const nextChar = unitId[prefix.length];
        if (/[A-Z0-9_]/.test(nextChar)) return commander;
      }
    }
  }
  return null;
}

async function readText(path) {
  return readFile(path, "utf8");
}

async function loadModFamilies(modRoot) {
  const familiesRaw = await loadCatalogFiles(modRoot, CATALOG_FILES, readText);
  const resolved = resolveAll(familiesRaw);
  return resolved;
}

// 将 src entry 的字段合并到 dst entry（dst 已存在）。
// 规则：dst 已有的字段保留（子覆盖父），dst 没有的字段从 src 继承。
// 数组：dst 没有的数组从 src 继承；dst 已有的数组保留（不追加，避免重复）。
// 这模拟 SC2 catalog 的跨 mod 继承：后加载的 mod 覆盖先加载的 mod 的同 ID entry，
// 但未指定的字段从前一个 mod 继承。
function mergeEntryFromBase(dst, src) {
  if (!src) return dst;
  // attrs
  for (const [k, v] of Object.entries(src.attrs || {})) {
    if (k === "id" || k === "parent") continue;
    if (!(k in dst.attrs)) dst.attrs[k] = v;
  }
  // fields
  for (const [k, v] of Object.entries(src.fields || {})) {
    if (!(k in dst.fields)) dst.fields[k] = v;
  }
  // arrays：仅当 dst 没有该数组时才继承（避免重复）
  for (const [name, arr] of Object.entries(src.arrays || {})) {
    if (!dst.arrays[name] || dst.arrays[name].length === 0) {
      dst.arrays[name] = arr.map((item) => ({ ...item }));
    }
  }
  return dst;
}

async function main() {
  console.log("[official] === 加载原版 mod ===");

  // 合并所有原版 mod 的 families
  let mergedUnits = new Map();
  let mergedWeapons = new Map();
  let mergedEffects = new Map();
  let mergedAbils = new Map();
  let mergedBehaviors = new Map();

  // 先加载基础游戏 mod（liberty/swarm/void），为 parent 解析提供基础单位数据
  // 这些 mod 不会被分类（基础游戏单位不属于任何合作指挥官），但它们的 LifeMax/CostResource 等字段
  // 会被 parent-resolver 继承到合作 mod 的派生单位上
  console.log("[official] --- 加载基础游戏 mod（parent 解析数据源）---");
  for (const mod of BASE_GAME_MODS) {
    const modRoot = resolve(workspaceRoot, mod.path.replace(/\//g, "\\"));
    if (!existsSync(modRoot)) {
      console.warn(`[official] base mod missing: ${mod.id} -> ${modRoot}`);
      continue;
    }
    const families = await loadModFamilies(modRoot);
    const unitFamily = families.Unit || new Map();
    const weaponFamily = families.Weapon || new Map();
    const effectFamily = families.Effect || new Map();
    const abilFamily = families.Abil || new Map();
    const behaviorFamily = families.Behavior || new Map();
    console.log(`[official] base/${mod.id}: ${unitFamily.size} units, ${weaponFamily.size} weapons, ${effectFamily.size} effects, ${abilFamily.size} abils, ${behaviorFamily.size} behaviors`);

    // 基础 mod 之间也按顺序合并（liberty -> swarm -> void -> ...）
    // 后加载的 mod 覆盖先加载的 mod 的同 ID entry，但未指定的字段从前一个继承
    for (const [id, entry] of unitFamily.entries()) {
      const existing = mergedUnits.get(id);
      if (existing) {
        // 已存在：用新 entry 覆盖，但继承缺失字段
        const merged = { ...entry };
        mergeEntryFromBase(merged, existing);
        mergedUnits.set(id, merged);
      } else {
        mergedUnits.set(id, entry);
      }
    }
    for (const [id, entry] of weaponFamily.entries()) {
      const existing = mergedWeapons.get(id);
      if (existing) {
        const merged = { ...entry };
        mergeEntryFromBase(merged, existing);
        mergedWeapons.set(id, merged);
      } else {
        mergedWeapons.set(id, entry);
      }
    }
    for (const [id, entry] of effectFamily.entries()) {
      const existing = mergedEffects.get(id);
      if (existing) {
        const merged = { ...entry };
        mergeEntryFromBase(merged, existing);
        mergedEffects.set(id, merged);
      } else {
        mergedEffects.set(id, entry);
      }
    }
    for (const [id, entry] of abilFamily.entries()) {
      const existing = mergedAbils.get(id);
      if (existing) {
        const merged = { ...entry };
        mergeEntryFromBase(merged, existing);
        mergedAbils.set(id, merged);
      } else {
        mergedAbils.set(id, entry);
      }
    }
    for (const [id, entry] of behaviorFamily.entries()) {
      const existing = mergedBehaviors.get(id);
      if (existing) {
        const merged = { ...entry };
        mergeEntryFromBase(merged, existing);
        mergedBehaviors.set(id, merged);
      } else {
        mergedBehaviors.set(id, entry);
      }
    }
  }

  console.log("[official] --- 加载合作 mod（共享 + 指挥官专属）---");
  for (const mod of OFFICIAL_MODS) {
    const modRoot = resolve(workspaceRoot, mod.path.replace(/\//g, "\\"));
    if (!existsSync(modRoot)) {
      console.warn(`[official] mod missing: ${mod.id} -> ${modRoot}`);
      continue;
    }
    const families = await loadModFamilies(modRoot);
    const unitFamily = families.Unit || new Map();
    const weaponFamily = families.Weapon || new Map();
    const effectFamily = families.Effect || new Map();
    const abilFamily = families.Abil || new Map();
    const behaviorFamily = families.Behavior || new Map();
    console.log(`[official] ${mod.id}: ${unitFamily.size} units, ${weaponFamily.size} weapons, ${effectFamily.size} effects, ${abilFamily.size} abils, ${behaviorFamily.size} behaviors`);

    // 合作 mod 覆盖基础 mod：合作 mod 的 entry 是"子"，基础 mod 的 entry 是"父"
    // 子覆盖父，但未指定的字段从父继承
    for (const [id, entry] of unitFamily.entries()) {
      const existing = mergedUnits.get(id);
      if (existing) {
        const merged = { ...entry };
        mergeEntryFromBase(merged, existing);
        mergedUnits.set(id, merged);
      } else {
        mergedUnits.set(id, entry);
      }
    }
    for (const [id, entry] of weaponFamily.entries()) {
      const existing = mergedWeapons.get(id);
      if (existing) {
        const merged = { ...entry };
        mergeEntryFromBase(merged, existing);
        mergedWeapons.set(id, merged);
      } else {
        mergedWeapons.set(id, entry);
      }
    }
    for (const [id, entry] of effectFamily.entries()) {
      const existing = mergedEffects.get(id);
      if (existing) {
        const merged = { ...entry };
        mergeEntryFromBase(merged, existing);
        mergedEffects.set(id, merged);
      } else {
        mergedEffects.set(id, entry);
      }
    }
    for (const [id, entry] of abilFamily.entries()) {
      const existing = mergedAbils.get(id);
      if (existing) {
        const merged = { ...entry };
        mergeEntryFromBase(merged, existing);
        mergedAbils.set(id, merged);
      } else {
        mergedAbils.set(id, entry);
      }
    }
    for (const [id, entry] of behaviorFamily.entries()) {
      const existing = mergedBehaviors.get(id);
      if (existing) {
        const merged = { ...entry };
        mergeEntryFromBase(merged, existing);
        mergedBehaviors.set(id, merged);
      } else {
        mergedBehaviors.set(id, entry);
      }
    }
  }

  console.log(`[official] 合并后: ${mergedUnits.size} units, ${mergedWeapons.size} weapons, ${mergedEffects.size} effects, ${mergedAbils.size} abils, ${mergedBehaviors.size} behaviors`);

  // 加载权重
  const weightsPath = join(balanceRoot, "config", "formula-weights.json");
  const weights = JSON.parse(await readFile(weightsPath, "utf8"));

  // 按指挥官分类提取单位
  const unitsByCommander = {};
  for (const commander of Object.keys(COMMANDER_INFO)) {
    unitsByCommander[commander] = [];
  }
  const unclassified = [];

  for (const [id, uEntry] of mergedUnits.entries()) {
    if (isAuxiliaryId(id)) continue;

    const commander = classifyCommander(id, uEntry);
    if (!commander) {
      // 仅记录有 LifeMax 的未分类单位（避免噪声）
      if (uEntry.fields && uEntry.fields.LifeMax) {
        unclassified.push(id);
      }
      continue;
    }

    const u = extractUnitMetrics(uEntry, mergedWeapons, mergedEffects, weights);
    if (!u) continue;
    if (shouldSkipUnit(u)) continue;

    u.commander = commander;
    u.commander_race = u.race || COMMANDER_INFO[commander].race;
    u.source_mod = "official";
    unitsByCommander[commander].push(u);
  }

  // 统计
  console.log("");
  console.log("[official] === 各指挥官单位数 ===");
  let totalUnits = 0;
  for (const commander of Object.keys(COMMANDER_INFO)) {
    const units = unitsByCommander[commander] || [];
    console.log(`  ${commander} (${COMMANDER_INFO[commander].zh}): ${units.length} 单位`);
    totalUnits += units.length;
  }
  console.log(`  未分类（有 LifeMax 的）: ${unclassified.length} 个 ID`);
  console.log(`  总计: ${totalUnits} 个原版单位`);

  // 评分
  console.log("");
  console.log("[official] === 评分 ===");
  const allOfficialUnits = [];
  for (const [commander, units] of Object.entries(unitsByCommander)) {
    for (const u of units) {
      const scored = { ...u, ...scoreUnit(u, weights) };
      allOfficialUnits.push(scored);
    }
  }

  // 计算分组统计
  const { enriched, groupStats } = computeGroupStatistics(allOfficialUnits, weights);
  console.log(`[official] 评分完成: ${enriched.length} 单位`);

  // 写入 JSON
  console.log("");
  console.log("[official] === 写入 JSON ===");
  await mkdir(OUTPUT_DIR, { recursive: true });

  // 1. 按指挥官分组的原始数据
  const officialByCommander = {};
  for (const commander of Object.keys(COMMANDER_INFO)) {
    const units = unitsByCommander[commander] || [];
    officialByCommander[commander] = {
      commander_zh: COMMANDER_INFO[commander].zh,
      commander_race: COMMANDER_INFO[commander].race,
      unit_count: units.length,
      units: units.map((u) => ({
        id: u.id,
        race: u.race,
        life_max: u.life_max,
        life_armor: u.life_armor,
        shields_max: u.shields_max,
        dps_general: u.dps_general,
        dps_light: u.dps_light,
        dps_armored: u.dps_armored,
        dps_massive: u.dps_massive,
        dps_air: u.dps_air,
        dps_ground: u.dps_ground,
        max_range: u.max_range,
        ehp: u.ehp,
        range_factor: u.range_factor,
        splash_factor: u.splash_factor,
        role_modifier: u.role_modifier,
        skill_value: u.skill_value,
        minerals: u.minerals,
        vespene: u.vespene,
        supply: u.supply,
        cost_normalized: u.cost_normalized,
        is_structure: u.is_structure,
        is_hero: u.is_hero,
        is_worker: u.is_worker,
        is_air: u.is_air,
        weapon_count: u.weapon_count,
        behavior_links: u.behavior_links || []
      }))
    };
  }

  await writeFile(
    join(OUTPUT_DIR, "official-units-raw.json"),
    JSON.stringify(
      {
        schema_version: 3,
        generated_at: new Date().toISOString(),
        source_mods: OFFICIAL_MODS.map((m) => m.id),
        classification: "Faction tag (11 commanders) + ID prefix (7 commanders)",
        commander_count: Object.keys(COMMANDER_INFO).length,
        total_units: totalUnits,
        unclassified_count: unclassified.length,
        commanders: officialByCommander
      },
      null,
      2
    ),
    "utf8"
  );
  console.log(`[official] 写入 official-units-raw.json`);

  // 2. 评分后数据
  const scoredByCommander = {};
  for (const u of enriched) {
    if (!scoredByCommander[u.commander]) {
      const info = COMMANDER_INFO[u.commander] || { zh: u.commander };
      scoredByCommander[u.commander] = {
        commander_zh: info.zh,
        units: []
      };
    }
    scoredByCommander[u.commander].units.push({
      id: u.id,
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
      S: u.S,
      primary_role: u.primary_role,
      z_internal: u.z_internal,
      z_official: u.z_official,
      is_outlier: u.is_outlier,
      outlier_direction: u.outlier_direction
    });
  }

  await writeFile(
    join(OUTPUT_DIR, "official-units-scored.json"),
    JSON.stringify(
      {
        schema_version: 3,
        generated_at: new Date().toISOString(),
        commanders: scoredByCommander
      },
      null,
      2
    ),
    "utf8"
  );
  console.log(`[official] 写入 official-units-scored.json`);

  // 3. 指挥官强度统计
  const commanderStats = [];
  for (const commander of Object.keys(COMMANDER_INFO)) {
    const units = unitsByCommander[commander] || [];
    const info = COMMANDER_INFO[commander];
    if (units.length === 0) {
      commanderStats.push({
        commander,
        commander_zh: info.zh,
        commander_race: info.race,
        unit_count: 0,
        avg_S: 0,
        median_S: 0,
        max_S: 0,
        min_S: 0,
        outlier_count: 0,
        outlier_rate: 0,
        avg_cost: 0,
        avg_ehp: 0,
        avg_dps: 0,
        insufficient_sample: true
      });
      continue;
    }
    const scored = enriched.filter((u) => u.commander === commander);
    const sValues = scored.map((u) => u.S).filter((v) => isFinite(v) && v > 0).sort((a, b) => a - b);
    const outlierCount = scored.filter((u) => u.is_outlier).length;
    const avgS = sValues.length ? sValues.reduce((a, b) => a + b, 0) / sValues.length : 0;
    const medianS = sValues.length ? sValues[Math.floor(sValues.length / 2)] : 0;
    const avgCost = scored.reduce((s, u) => s + (u.cost_normalized || 0), 0) / scored.length;
    const avgEhp = scored.reduce((s, u) => s + (u.ehp || 0), 0) / scored.length;
    const avgDps = scored.reduce((s, u) => s + (u.dps_general || 0), 0) / scored.length;

    commanderStats.push({
      commander,
      commander_zh: info.zh,
      commander_race: info.race,
      unit_count: units.length,
      avg_S: Number(avgS.toFixed(3)),
      median_S: Number(medianS.toFixed(3)),
      max_S: Number((sValues[sValues.length - 1] || 0).toFixed(3)),
      min_S: Number((sValues[0] || 0).toFixed(3)),
      outlier_count: outlierCount,
      outlier_rate: Number((outlierCount / units.length).toFixed(3)),
      avg_cost: Number(avgCost.toFixed(1)),
      avg_ehp: Number(avgEhp.toFixed(0)),
      avg_dps: Number(avgDps.toFixed(1)),
      insufficient_sample: units.length < 5
    });
  }

  // 按 avg_S 降序排序
  commanderStats.sort((a, b) => {
    if (a.insufficient_sample !== b.insufficient_sample) return a.insufficient_sample ? 1 : -1;
    return b.avg_S - a.avg_S;
  });

  await writeFile(
    join(OUTPUT_DIR, "official-commander-stats.json"),
    JSON.stringify(
      {
        schema_version: 3,
        generated_at: new Date().toISOString(),
        commanders: commanderStats
      },
      null,
      2
    ),
    "utf8"
  );
  console.log(`[official] 写入 official-commander-stats.json`);

  // 控制台输出排名
  console.log("");
  console.log("[official] === 原版 18 位指挥官强度排名（按 avg_S 降序）===");
  console.log("  排名 | 指挥官 | 单位数 | avg_S | median_S | max_S | 离群率 | avg_cost | avg_ehp | avg_dps");
  commanderStats.forEach((c, i) => {
    const mark = c.insufficient_sample ? " (N/A)" : "";
    console.log(`  ${i + 1}. ${c.commander} (${c.commander_zh})${mark} | ${c.unit_count} | ${c.avg_S} | ${c.median_S} | ${c.max_S} | ${(c.outlier_rate * 100).toFixed(1)}% | ${c.avg_cost} | ${c.avg_ehp} | ${c.avg_dps}`);
  });

  console.log("");
  console.log("[official] === 完成 ===");
  console.log(`[official] 输出目录: ${OUTPUT_DIR}`);
  console.log(`[official] 总单位数: ${totalUnits}`);
}

main().catch((err) => {
  console.error("[official] FATAL:", err);
  console.error(err.stack);
  process.exit(1);
});
