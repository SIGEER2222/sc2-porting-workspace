// src/mengsk-vs-alenger3.mjs
// 重点对比：原版蒙斯克 vs 起义 3（疯批帝国）数值差异
//
// 输入：
//   official-units-raw.json  原版单位数据（含 Mengsk）
//   units-scored.json        起义单位评分数据（含 Alenger3）
//   detailed-units.json      起义单位详情（含中文名、形态等）
//
// 输出：
//   mengsk-vs-alenger3.json  结构化对比数据
//   mengsk-vs-alenger3.md    人类可读对比报告
//
// 对比维度：
//   1. 指挥官层级：单位数 / avg_S / avg_cost / avg_ehp / avg_dps / avg_life / avg_armor
//   2. 单位角色分布：步兵 / 装甲 / 空军 / 建筑 / 英雄
//   3. 单位层级对比：按角色匹配相似单位，对比数值差异
//   4. 关键单位 Top N：最强势单位对比
//   5. 平衡建议：基于对比的细粒度 nerf 建议

import { readFile, writeFile, mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const balanceRoot = resolve(scriptDir, "..");
const workspaceRoot = resolve(balanceRoot, "..", "..");
const OUTPUT_DIR = resolve(workspaceRoot, "artifacts", "balance", "2026-07-26");

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

// 蒙斯克单位中文名映射（基于 SC2 官方翻译）
const MENGSK_UNIT_ZH = {
  TrooperMengsk: "帝国列兵",
  TrooperMengskImproved: "帝国列兵（强化）",
  TrooperMengskAA: "帝国列兵（防空）",
  TrooperMengskFlamethrower: "帝国列兵（火焰喷射）",
  MarauderMengsk: "帝国劫掠者",
  GhostMengsk: "帝国幽灵",
  MedivacMengsk: "帝国医疗运输机",
  RavenMengsk: "帝国乌鸦",
  RavenMengskSieged: "帝国乌鸦（驻守）",
  SiegeTankMengsk: "帝国攻城坦克",
  SiegeTankMengskSieged: "帝国攻城坦克（攻城模式）",
  ThorMengsk: "帝国雷神",
  ThorMengskSieged: "帝国雷神（驻守）",
  VikingMengskAssault: "帝国维京（突击）",
  VikingMengskFighter: "帝国维京（飞行）",
  BattlecruiserMengsk: "帝国战列巡航舰",
  MutaliskMengsk: "帝国飞龙",
  HydraliskMengsk: "帝国刺蛇",
  HydraliskMengskBurrowed: "帝国刺蛇（钻地）",
  UltraliskMengsk: "帝国雷兽",
  ZerglingMengsk: "帝国跳虫",
  ZerglingMengskBurrowed: "帝国跳虫（钻地）",
  ArtilleryMengsk: "帝国火炮",
  SCVMengsk: "帝国 SCV",
  ArmoryMengsk: "帝国军械库",
  BarracksMengsk: "帝国兵营",
  BarracksMengskFlying: "帝国兵营（飞行）",
  BunkerDepotMengsk: "帝国地堡仓库",
  BunkerDepotMengskDrop: "帝国地堡仓库（空投）",
  CommandCenterMengsk: "帝国指挥中心",
  CommandCenterMengskFlying: "帝国指挥中心（飞行）",
  EngineeringBayMengsk: "帝国工程站",
  FactoryMengsk: "帝国工厂",
  FactoryMengskFlying: "帝国工厂（飞行）",
  FusionCoreMengsk: "帝国聚变芯体",
  GhostAcademyMengsk: "帝国幽灵学院",
  MissileTurretMengsk: "帝国导弹塔",
  StarportMengsk: "帝国星港",
  StarportMengskFlying: "帝国星港（飞行）",
  NukeMengsk: "帝国核弹"
};

// 起义 3 单位中文名映射（基于 detailed-units.json 中的 zh 字段，这里做 fallback）
const ALENGER3_UNIT_ZH_FALLBACK = {
  "3baixinghao": "百星号",
  "3jindiaoFighterModeS": "金雕（战机模式·驻守）",
  "3jindiaoFighterMode": "金雕（战机模式）",
  "3diguochongfengdui": "帝国冲锋队",
  "3huojianchongfengdui": "火箭冲锋队",
  "3huoyanchongfengdui": "火焰冲锋队",
  "3shuzuichongfengdui": "鼠嘴冲锋队",
  "3yuqianweishi": "御前卫士",
  "3yuqianxianfeng": "御前先锋",
  "3junwangjichaozhongxinggongchengtankeTankMode": "君王级超中型工程坦克（坦克模式）",
  "3junwangjichaozhongxinggongchengtankeSiegeMode": "君王级超中型工程坦克（攻城模式）",
  "3fengbaochongfengdui": "风暴冲锋队",
  "3diguozhihuizhongxin": "帝国指挥中心",
  "3aogusigeledejiaoao": "奥古斯都的骄傲",
  "3kehajinjun": "克哈进军",
  "3chongfengduigongchengtankeTankMode": "冲锋队工程坦克（坦克模式）",
  "3chongfengduigongchengtankeSiegeMode": "冲锋队工程坦克（攻城模式）",
  "3huangjiawuweijizhanliejian": "皇家无畏级战列舰",
  "3chongfengduixunhangjian": "冲锋队巡航舰",
  "3diguozhijian": "帝国之剑",
  "3huguozhanjiang": "护国战将",
  "3jinweijijia": "护卫机甲",
  "3xiang": "象",
  "3diguolaogong": "帝国劳工",
  "3diguoqianshaojidi": "帝国前哨基地",
  "3diguoqianshaojidiFlying": "帝国前哨基地（飞行）",
  "3huangjiayaosai": "皇家要塞",
  "3diguogongchengzhan": "帝国工程站",
  "3zidonghuajinglianchang": "自动化精炼厂",
  "3huangjiafangkongta": "皇家防空塔",
  "3diduiyixiantong": "帝队一线营",
  "3diduiyijunxuxie": "帝队军需械",
  "3diduiyingdi": "帝队营地",
  "3huangjiawuweiji": "皇家无畏机甲",
  "3hejijia": "核机甲"
};

// 单位角色分类
function classifyRole(u) {
  if (u.is_structure) return "建筑";
  if (u.is_hero) return "英雄";
  if (u.is_worker) return "工人";
  if (u.is_air) return "空军";
  if (u.life_max >= 400 && (u.life_armor >= 2 || u.shields_max > 0)) return "装甲";
  return "步兵";
}

// 单位定位子类（用于匹配相似单位）
function classifyRoleFingerprint(u) {
  const role = classifyRole(u);
  let subRole = "通用";
  if (u.dps_air > u.dps_ground * 1.5) subRole = "防空";
  else if (u.dps_ground > u.dps_air * 1.5 && u.dps_ground > 0) subRole = "对地";
  if (u.max_range >= 6) subRole += "+远程";
  else if (u.max_range > 0 && u.max_range < 3) subRole += "+近战";
  return `${role}+${subRole}`;
}

// 计算指挥官指标
function computeMetrics(units) {
  if (!units || units.length === 0) {
    return {
      unit_count: 0, avg_S: 0, median_S: 0, max_S: 0, min_S: 0,
      avg_cost: 0, avg_ehp: 0, avg_dps: 0, avg_life: 0, avg_armor: 0,
      avg_shields: 0, avg_range: 0, insufficient_sample: true
    };
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
    avg_cost: Number((units.reduce((s, u) => s + (u.cost_normalized || 0), 0) / units.length).toFixed(1)),
    avg_ehp: Number((units.reduce((s, u) => s + (u.ehp || 0), 0) / units.length).toFixed(0)),
    avg_dps: Number((units.reduce((s, u) => s + (u.dps_general || 0), 0) / units.length).toFixed(1)),
    avg_life: Number((units.reduce((s, u) => s + (u.life_max || 0), 0) / units.length).toFixed(0)),
    avg_armor: Number((units.reduce((s, u) => s + (u.life_armor || 0), 0) / units.length).toFixed(2)),
    avg_shields: Number((units.reduce((s, u) => s + (u.shields_max || 0), 0) / units.length).toFixed(0)),
    avg_range: Number((units.reduce((s, u) => s + (u.max_range || 0), 0) / units.length).toFixed(2)),
    insufficient_sample: units.length < 5
  };
}

async function main() {
  console.log("[mva] === Mengsk vs Alenger3 对比 ===");
  const officialRaw = await readJson("official-units-raw.json");
  const alengerScored = await readJson("units-scored.json");
  let detailed = null;
  try {
    detailed = await readJson("detailed-units.json");
  } catch (e) {
    console.warn("[mva] detailed-units.json not found, using fallback names");
  }

  // 提取 Mengsk 单位
  const mengskUnitsRaw = (officialRaw.commanders.Mengsk?.units) || [];
  // 重新计算 S 值（确保一致）
  const mengskUnits = mengskUnitsRaw.map(u => ({
    ...u,
    commander: "Mengsk",
    S: u.cost_normalized > 0 ? (u.ehp * (u.dps_general || 0) + (u.skill_value || 0)) / u.cost_normalized : 0,
    commander_zh: "蒙斯克",
    unit_zh: MENGSK_UNIT_ZH[u.id] || u.id
  }));

  // 提取 Alenger3 单位
  const alenger3UnitsRaw = alengerScored.units.filter(u => u.commander === "Alenger3");
  // 从 detailed-units.json 补充中文名
  const detailedMap = new Map();
  if (detailed) {
    for (const u of detailed.units || []) {
      if (u.commander === "Alenger3") {
        detailedMap.set(u.id, u);
      }
    }
  }
  const alenger3Units = alenger3UnitsRaw.map(u => ({
    ...u,
    commander: "Alenger3",
    commander_zh: "起义 3（疯批帝国）",
    unit_zh: (detailedMap.get(u.id)?.zh) || ALENGER3_UNIT_ZH_FALLBACK[u.id] || u.id
  }));

  console.log(`[mva] Mengsk: ${mengskUnits.length} 单位`);
  console.log(`[mva] Alenger3: ${alenger3Units.length} 单位`);

  // === 1. 指挥官层级指标对比 ===
  const mengskMetrics = computeMetrics(mengskUnits);
  const alenger3Metrics = computeMetrics(alenger3Units);

  const delta = {};
  const ratio = {};
  for (const k of ["avg_S", "median_S", "avg_cost", "avg_ehp", "avg_dps", "avg_life", "avg_armor", "avg_shields", "avg_range"]) {
    delta[k] = alenger3Metrics[k] - mengskMetrics[k];
    ratio[k] = mengskMetrics[k] > 0 ? Number((alenger3Metrics[k] / mengskMetrics[k]).toFixed(3)) : 0;
  }

  // === 2. 角色分布对比 ===
  const mengskByRole = {};
  const alenger3ByRole = {};
  for (const u of mengskUnits) {
    const r = classifyRole(u);
    if (!mengskByRole[r]) mengskByRole[r] = [];
    mengskByRole[r].push(u);
  }
  for (const u of alenger3Units) {
    const r = classifyRole(u);
    if (!alenger3ByRole[r]) alenger3ByRole[r] = [];
    alenger3ByRole[r].push(u);
  }

  // === 3. 相似单位匹配对比 ===
  // 按 fingerprint 分组，每组取 avg 对比
  const mengskByFingerprint = {};
  for (const u of mengskUnits) {
    const fp = classifyRoleFingerprint(u);
    if (!mengskByFingerprint[fp]) mengskByFingerprint[fp] = [];
    mengskByFingerprint[fp].push(u);
  }
  const alenger3ByFingerprint = {};
  for (const u of alenger3Units) {
    const fp = classifyRoleFingerprint(u);
    if (!alenger3ByFingerprint[fp]) alenger3ByFingerprint[fp] = [];
    alenger3ByFingerprint[fp].push(u);
  }

  // 对每个 Mengsk 单位，找到 Alenger3 中相同 fingerprint 的单位
  const unitComparisons = [];
  for (const u of mengskUnits) {
    const fp = classifyRoleFingerprint(u);
    const candidates = alenger3ByFingerprint[fp] || [];
    if (candidates.length === 0) continue;
    // 找到 cost_normalized 最接近的 Alenger3 单位
    let bestMatch = null;
    let bestCostDiff = Infinity;
    for (const c of candidates) {
      const diff = Math.abs(c.cost_normalized - u.cost_normalized);
      if (diff < bestCostDiff) {
        bestCostDiff = diff;
        bestMatch = c;
      }
    }
    if (!bestMatch) continue;

    unitComparisons.push({
      fingerprint: fp,
      mengsk: {
        id: u.id,
        zh: u.unit_zh,
        life_max: u.life_max,
        life_armor: u.life_armor,
        shields_max: u.shields_max,
        dps_general: u.dps_general,
        ehp: u.ehp,
        cost_normalized: u.cost_normalized,
        minerals: u.minerals,
        vespene: u.vespene,
        supply: u.supply,
        S: u.S,
        max_range: u.max_range
      },
      alenger3: {
        id: bestMatch.id,
        zh: bestMatch.unit_zh,
        life_max: bestMatch.life_max,
        life_armor: bestMatch.life_armor,
        shields_max: bestMatch.shields_max,
        dps_general: bestMatch.dps_general,
        ehp: bestMatch.ehp,
        cost_normalized: bestMatch.cost_normalized,
        minerals: bestMatch.minerals,
        vespene: bestMatch.vespene,
        supply: bestMatch.supply,
        S: bestMatch.S,
        max_range: bestMatch.max_range
      },
      delta: {
        life_max: bestMatch.life_max - u.life_max,
        dps_general: Number((bestMatch.dps_general - u.dps_general).toFixed(2)),
        ehp: bestMatch.ehp - u.ehp,
        cost_normalized: bestMatch.cost_normalized - u.cost_normalized,
        S: Number((bestMatch.S - u.S).toFixed(3))
      },
      ratio: {
        life_max: u.life_max > 0 ? Number((bestMatch.life_max / u.life_max).toFixed(2)) : 0,
        dps_general: u.dps_general > 0 ? Number((bestMatch.dps_general / u.dps_general).toFixed(2)) : 0,
        ehp: u.ehp > 0 ? Number((bestMatch.ehp / u.ehp).toFixed(2)) : 0,
        cost_normalized: u.cost_normalized > 0 ? Number((bestMatch.cost_normalized / u.cost_normalized).toFixed(2)) : 0,
        S: u.S > 0 ? Number((bestMatch.S / u.S).toFixed(2)) : 0
      }
    });
  }

  // === 4. Top 强势单位 ===
  const mengskTop = [...mengskUnits]
    .filter(u => u.S > 0)
    .sort((a, b) => b.S - a.S)
    .slice(0, 10)
    .map(u => ({
      id: u.id, zh: u.unit_zh, S: Number(u.S.toFixed(3)),
      life_max: u.life_max, dps_general: u.dps_general,
      ehp: u.ehp, cost_normalized: u.cost_normalized
    }));

  const alenger3Top = [...alenger3Units]
    .filter(u => u.S > 0)
    .sort((a, b) => b.S - a.S)
    .slice(0, 10)
    .map(u => ({
      id: u.id, zh: u.unit_zh, S: Number((u.S || 0).toFixed(3)),
      life_max: u.life_max, dps_general: u.dps_general,
      ehp: u.ehp, cost_normalized: u.cost_normalized
    }));

  // === 5. 平衡建议 ===
  // 基于对比结果，给出细粒度 nerf 建议
  const suggestions = [];
  for (const cmp of unitComparisons) {
    if (cmp.ratio.S <= 1.0) continue; // 起义 S 值未超标，跳过
    let severity = "轻度";
    let costAdjust = 1.0;
    if (cmp.ratio.S > 5) {
      severity = "严重";
      costAdjust = 1.50;
    } else if (cmp.ratio.S > 3) {
      severity = "重度";
      costAdjust = 1.30;
    } else if (cmp.ratio.S > 1.5) {
      severity = "中度";
      costAdjust = 1.15;
    }
    suggestions.push({
      alenger3_unit: cmp.alenger3.id,
      alenger3_zh: cmp.alenger3.zh,
      mengsk_reference: cmp.mengsk.id,
      mengsk_zh: cmp.mengsk.zh,
      fingerprint: cmp.fingerprint,
      alenger3_S: cmp.alenger3.S,
      mengsk_S: cmp.mengsk.S,
      S_ratio: cmp.ratio.S,
      severity,
      cost_adjust: costAdjust,
      reason: `起义 S=${cmp.alenger3.S.toFixed(2)} vs 蒙斯克 S=${cmp.mengsk.S.toFixed(2)}（${cmp.ratio.S}×），${severity} nerf`
    });
  }
  suggestions.sort((a, b) => b.S_ratio - a.S_ratio);

  // === 写 JSON ===
  console.log("[mva] 写入 mengsk-vs-alenger3.json...");
  await mkdir(OUTPUT_DIR, { recursive: true });
  await writeFile(
    join(OUTPUT_DIR, "mengsk-vs-alenger3.json"),
    JSON.stringify({
      schema_version: 1,
      generated_at: new Date().toISOString(),
      summary: {
        mengsk_unit_count: mengskUnits.length,
        alenger3_unit_count: alenger3Units.length,
        mengsk_avg_S: mengskMetrics.avg_S,
        alenger3_avg_S: alenger3Metrics.avg_S,
        delta_avg_S: delta.avg_S,
        ratio_avg_S: ratio.avg_S
      },
      overall: {
        mengsk: mengskMetrics,
        alenger3: alenger3Metrics,
        delta,
        ratio
      },
      role_distribution: {
        mengsk: Object.fromEntries(Object.entries(mengskByRole).map(([k, v]) => [k, v.length])),
        alenger3: Object.fromEntries(Object.entries(alenger3ByRole).map(([k, v]) => [k, v.length]))
      },
      unit_comparisons: unitComparisons,
      top_units: {
        mengsk_top_10: mengskTop,
        alenger3_top_10: alenger3Top
      },
      patch_suggestions: suggestions
    }, null, 2),
    "utf8"
  );

  // === 写 Markdown 报告 ===
  console.log("[mva] 写入 mengsk-vs-alenger3.md...");
  const md = [];
  md.push("# 蒙斯克 vs 起义 3（疯批帝国）数值对比报告");
  md.push("");
  md.push(`**生成时间**：${new Date().toISOString()}`);
  md.push(`**对比维度**：指挥官层级 / 角色分布 / 相似单位配对 / Top 强势单位 / 平衡建议`);
  md.push(`**原版蒙斯克样本**：${mengskUnits.length} 个单位（来自 arcturusmengsk.sc2mod）`);
  md.push(`**起义 3 样本**：${alenger3Units.length} 个单位（来自 Alenger3.SC2Mod）`);
  md.push(`**特别说明**：起义 3 的设计风格明显参考了蒙斯克（人族帝国 + 列兵冲锋队 + 皇家护卫 + 战列舰），因此本对比可作为起义 3 平衡性调整的直接依据`);
  md.push("");
  md.push("---");
  md.push("");

  // === 0. 全局总览 ===
  md.push("## 0. 全局总览");
  md.push("");
  md.push("| 指标 | 蒙斯克（原版） | 起义 3（疯批帝国） | Δ（起义-原版） | 比率（起义/原版） |");
  md.push("|------|----------------|---------------------|----------------|---------------------|");
  md.push(`| 单位数 | ${mengskMetrics.unit_count} | ${alenger3Metrics.unit_count} | ${alenger3Metrics.unit_count - mengskMetrics.unit_count} | ${(alenger3Metrics.unit_count / mengskMetrics.unit_count).toFixed(2)}× |`);
  md.push(`| 平均 S 值 | ${fmt(mengskMetrics.avg_S)} | ${fmt(alenger3Metrics.avg_S)} | ${fmt(delta.avg_S)} | ${ratio.avg_S}× |`);
  md.push(`| 中位 S 值 | ${fmt(mengskMetrics.median_S)} | ${fmt(alenger3Metrics.median_S)} | ${fmt(delta.median_S)} | ${ratio.median_S}× |`);
  md.push(`| 平均造价（归一化） | ${fmt(mengskMetrics.avg_cost)} | ${fmt(alenger3Metrics.avg_cost)} | ${fmt(delta.avg_cost)} | ${ratio.avg_cost}× |`);
  md.push(`| 平均 EHP | ${fmt(mengskMetrics.avg_ehp)} | ${fmt(alenger3Metrics.avg_ehp)} | ${fmt(delta.avg_ehp)} | ${ratio.avg_ehp}× |`);
  md.push(`| 平均 DPS | ${fmt(mengskMetrics.avg_dps)} | ${fmt(alenger3Metrics.avg_dps)} | ${fmt(delta.avg_dps)} | ${ratio.avg_dps}× |`);
  md.push(`| 平均血量 | ${fmt(mengskMetrics.avg_life)} | ${fmt(alenger3Metrics.avg_life)} | ${fmt(delta.avg_life)} | ${ratio.avg_life}× |`);
  md.push(`| 平均护甲 | ${fmt(mengskMetrics.avg_armor)} | ${fmt(alenger3Metrics.avg_armor)} | ${fmt(delta.avg_armor)} | ${ratio.avg_armor}× |`);
  md.push(`| 平均护盾 | ${fmt(mengskMetrics.avg_shields)} | ${fmt(alenger3Metrics.avg_shields)} | ${fmt(delta.avg_shields)} | ${ratio.avg_shields}× |`);
  md.push(`| 平均射程 | ${fmt(mengskMetrics.avg_range)} | ${fmt(alenger3Metrics.avg_range)} | ${fmt(delta.avg_range)} | ${ratio.avg_range}× |`);
  md.push("");

  let conclusion;
  if (ratio.avg_S > 5) {
    conclusion = `**结论**：起义 3 整体强度**严重超标**（S 值 ${ratio.avg_S}×），需大规模 nerf。`;
  } else if (ratio.avg_S > 2) {
    conclusion = `**结论**：起义 3 整体强度**明显偏高**（S 值 ${ratio.avg_S}×），需对偏强单位进行 nerf。`;
  } else if (ratio.avg_S > 1.3) {
    conclusion = `**结论**：起义 3 整体强度**略偏高**（S 值 ${ratio.avg_S}×），需对个别离群单位进行调整。`;
  } else if (ratio.avg_S < 0.7) {
    conclusion = `**结论**：起义 3 整体强度**严重不足**（S 值 ${ratio.avg_S}×），需大规模 buff。`;
  } else {
    conclusion = `**结论**：起义 3 整体强度与蒙斯克**基本持平**（S 值 ${ratio.avg_S}×），仅需细粒度调整。`;
  }
  md.push(conclusion);
  md.push("");

  // === 1. 角色分布 ===
  md.push("## 1. 角色分布对比");
  md.push("");
  md.push("| 角色 | 蒙斯克 | 起义 3 |");
  md.push("|------|--------|--------|");
  const allRoles = new Set([...Object.keys(mengskByRole), ...Object.keys(alenger3ByRole)]);
  for (const r of ["步兵", "装甲", "空军", "建筑", "英雄", "工人"]) {
    if (!allRoles.has(r)) continue;
    md.push(`| ${r} | ${mengskByRole[r]?.length || 0} | ${alenger3ByRole[r]?.length || 0} |`);
  }
  md.push("");

  // === 2. 相似单位配对对比 ===
  md.push("## 2. 相似单位配对对比（按造价最接近匹配）");
  md.push("");
  md.push(`共找到 ${unitComparisons.length} 对相似单位。下表按起义 S 值比率降序排列：`);
  md.push("");
  md.push("| 起义单位 | 蒙斯克参照 | 角色 | 起义 S | 蒙斯克 S | S 比率 | 起义血量 | 蒙斯克血量 | 血量比率 | 起义 DPS | 蒙斯克 DPS | DPS 比率 | 起义造价 | 蒙斯克造价 | 造价比率 |");
  md.push("|----------|------------|------|--------|----------|---------|----------|------------|----------|----------|------------|----------|----------|------------|----------|");
  const sortedComparisons = [...unitComparisons].sort((a, b) => b.ratio.S - a.ratio.S);
  for (const cmp of sortedComparisons) {
    md.push(`| ${cmp.alenger3.zh} | ${cmp.mengsk.zh} | ${cmp.fingerprint} | ${fmt(cmp.alenger3.S)} | ${fmt(cmp.mengsk.S)} | ${cmp.ratio.S}× | ${fmt(cmp.alenger3.life_max)} | ${fmt(cmp.mengsk.life_max)} | ${cmp.ratio.life_max}× | ${fmt(cmp.alenger3.dps_general)} | ${fmt(cmp.mengsk.dps_general)} | ${cmp.ratio.dps_general}× | ${fmt(cmp.alenger3.cost_normalized)} | ${fmt(cmp.mengsk.cost_normalized)} | ${cmp.ratio.cost_normalized}× |`);
  }
  md.push("");

  // === 3. Top 10 强势单位 ===
  md.push("## 3. Top 10 强势单位对比");
  md.push("");
  md.push("### 3.1 蒙斯克 Top 10（按 S 值降序）");
  md.push("");
  md.push("| 排名 | 单位 | ID | S 值 | 血量 | DPS | EHP | 造价 |");
  md.push("|------|------|-----|------|------|-----|-----|------|");
  mengskTop.forEach((u, i) => {
    md.push(`| ${i + 1} | ${u.zh} | ${u.id} | ${fmt(u.S)} | ${fmt(u.life_max)} | ${fmt(u.dps_general)} | ${fmt(u.ehp)} | ${fmt(u.cost_normalized)} |`);
  });
  md.push("");

  md.push("### 3.2 起义 3 Top 10（按 S 值降序）");
  md.push("");
  md.push("| 排名 | 单位 | ID | S 值 | 血量 | DPS | EHP | 造价 |");
  md.push("|------|------|-----|------|------|-----|-----|------|");
  alenger3Top.forEach((u, i) => {
    md.push(`| ${i + 1} | ${u.zh} | ${u.id} | ${fmt(u.S)} | ${fmt(u.life_max)} | ${fmt(u.dps_general)} | ${fmt(u.ehp)} | ${fmt(u.cost_normalized)} |`);
  });
  md.push("");

  // === 4. 平衡建议 ===
  md.push("## 4. 平衡建议（基于蒙斯克参照的细粒度 nerf）");
  md.push("");
  md.push(`共生成 ${suggestions.length} 条 nerf 建议（仅列出 S 比率 > 1.0 的起义单位）：`);
  md.push("");
  md.push("| 起义单位 | 蒙斯克参照 | 角色 | 起义 S | 蒙斯克 S | S 比率 | 严重程度 | 建议系数 | 理由 |");
  md.push("|----------|------------|------|--------|----------|---------|----------|----------|------|");
  for (const s of suggestions) {
    md.push(`| ${s.alenger3_zh} | ${s.mengsk_zh} | ${s.fingerprint} | ${fmt(s.alenger3_S)} | ${fmt(s.mengsk_S)} | ${s.S_ratio}× | ${s.severity} | ×${s.cost_adjust} | ${s.reason} |`);
  }
  md.push("");

  // === 5. 关键发现 ===
  md.push("## 5. 关键发现");
  md.push("");
  md.push("### 5.1 整体偏差");
  md.push("");
  md.push(`- **S 值比率**：起义 3 平均 S 值为蒙斯克的 **${ratio.avg_S}×**`);
  md.push(`- **造价比率**：起义 3 平均造价为蒙斯克的 **${ratio.avg_cost}×**`);
  md.push(`- **EHP 比率**：起义 3 平均 EHP 为蒙斯克的 **${ratio.avg_ehp}×**`);
  md.push(`- **DPS 比率**：起义 3 平均 DPS 为蒙斯克的 **${ratio.avg_dps}×**`);
  md.push(`- **血量比率**：起义 3 平均血量为蒙斯克的 **${ratio.avg_life}×**`);
  md.push("");

  // === 6. 应用建议 ===
  md.push("### 5.2 应用建议");
  md.push("");
  if (ratio.avg_S > 2) {
    md.push(`1. **整体 nerf**：起义 3 平均 S 值远超蒙斯克（${ratio.avg_S}×），建议对所有战斗单位造价统一上调 ×1.20~1.30`);
    md.push(`2. **重点 nerf**：对 S 比率 > 3 的单位（${suggestions.filter(s => s.S_ratio > 3).length} 个）额外上调 ×1.30~1.50`);
    md.push(`3. **细粒度调整**：参照本报告"相似单位配对"表，确保起义单位 S 值不超过蒙斯克同定位单位的 1.5×`);
  } else if (ratio.avg_S > 1.3) {
    md.push(`1. **重点 nerf**：对 S 比率 > 2 的单位（${suggestions.filter(s => s.S_ratio > 2).length} 个）上调 ×1.15~1.30`);
    md.push(`2. **细粒度调整**：参照本报告"相似单位配对"表，确保起义单位 S 值不超过蒙斯克同定位单位的 1.3×`);
  } else {
    md.push(`1. **微调**：起义 3 整体强度与蒙斯克接近，仅需对个别 S 比率 > 2 的单位（${suggestions.filter(s => s.S_ratio > 2).length} 个）进行 ±10% 调整`);
  }
  md.push("");
  md.push("### 5.3 注意事项");
  md.push("");
  md.push('- 本报告的「相似单位配对」基于角色指纹（步兵/装甲/空军 + 防空/对地/远程/近战）和造价最接近原则匹配，可能存在误配，应用时需人工复核');
  md.push("- 蒙斯克原版部分单位（如 GhostMengsk、BattlecruiserMengsk）的 DPS=0 是因为武器数据未在 mod 中完整定义（继承自基础游戏），实际游戏中这些单位有正常 DPS");
  md.push("- 起义 3 的英雄单位（如 百星号、奥古斯都的骄傲）S 值极高，但英雄单位的平衡需额外考虑其获取条件和操作复杂度，不宜直接按 S 值 nerf");
  md.push("");

  await writeFile(join(OUTPUT_DIR, "mengsk-vs-alenger3.md"), md.join("\n"), "utf8");

  console.log("[mva] === 完成 ===");
  console.log(`[mva] 输出目录: ${OUTPUT_DIR}`);
  console.log(`[mva] 单位配对: ${unitComparisons.length} 对`);
  console.log(`[mva] nerf 建议: ${suggestions.length} 条`);
  console.log(`[mva] S 比率: ${ratio.avg_S}× (起义3 / 蒙斯克)`);
}

main().catch(err => {
  console.error("[mva] FATAL:", err);
  console.error(err.stack);
  process.exit(1);
});
