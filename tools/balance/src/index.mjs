// src/index.mjs
// CLI 入口
//
// 用法：
//   node tools/balance/src/index.mjs analyze --all
//   node tools/balance/src/index.mjs extract --commander Alenger3
//   node tools/balance/src/index.mjs score --input units-raw.json
//   node tools/balance/src/index.mjs outliers --input units-scored.json
//
// 完整流程 `analyze --all`：
//   1. 加载 12 起义 mod + 官方 mod
//   2. 解析 XML、合并 parent、追踪 effect 链
//   3. 提取单位指标
//   4. 评分
//   5. 离群分析
//   6. 生成报告（JSON + Markdown）

import { readFile, mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

import { parseCatalogXml, loadCatalogFiles } from "./xml-parser.mjs";
import { resolveAll } from "./parent-resolver.mjs";
import { extractUnitMetrics, classifyRoles } from "./metrics.mjs";
import {
  scoreUnit,
  computeGroupStatistics,
  computeZScores,
  findOutliers,
  suggestPatches,
  computeCounterMatrix
} from "./formula.mjs";
import * as reporter from "./reporter.mjs";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const balanceRoot = resolve(scriptDir, "..");
const workspaceRoot = resolve(balanceRoot, "..", ".."); // sc2-porting-workspace/

const OUTPUT_DIR = resolve(workspaceRoot, "artifacts", "balance", "2026-07-26");

const CATALOG_FILES = ["UnitData.xml", "WeaponData.xml", "EffectData.xml", "AbilData.xml", "BehaviorData.xml"];

async function readJsonSafe(path) {
  if (!existsSync(path)) return null;
  return JSON.parse(await readFile(path, "utf8"));
}

async function readText(path) {
  return readFile(path, "utf8");
}

// 加载一个 mod 的 catalog，返回合并 parent 后的 families
async function loadModCatalog(modRootAbs, config) {
  const familiesRaw = await loadCatalogFiles(modRootAbs, CATALOG_FILES, readText);
  const resolved = resolveAll(familiesRaw);
  return resolved;
}

// 判定 ID 是否为辅助单位（不应计入分析）
function isAuxiliaryId(id, auxiliarySuffixes) {
  for (const suffix of auxiliarySuffixes) {
    if (id.includes(suffix)) return true;
  }
  return false;
}

// 判定是否应跳过该单位
function shouldSkipUnit(unit, weights) {
  if (!unit.life_max || unit.life_max <= 0) return true;
  if (unit.life_max > 100000) return true;
  if (unit.minerals === 0 && unit.vespene === 0) return true;
  return false;
}

// 主流程
async function runAnalyzeAll() {
  const configPath = join(balanceRoot, "config", "commanders.json");
  const weightsPath = join(balanceRoot, "config", "formula-weights.json");
  const config = JSON.parse(await readFile(configPath, "utf8"));
  const weights = JSON.parse(await readFile(weightsPath, "utf8"));

  console.log(`[balance] workspace root: ${workspaceRoot}`);
  console.log(`[balance] output dir: ${OUTPUT_DIR}`);

  // === 加载起义 mod ===
  console.log("[balance] === 加载起义 mod ===");
  const alengerUnitsByCommander = []; // [{ commander, modRoot, units: [unit...] }]
  for (const mod of config.alengerMods) {
    const modRoot = resolve(workspaceRoot, mod.path.replace(/\//g, sep));
    if (!existsSync(modRoot)) {
      console.warn(`[balance] mod missing: ${mod.id} -> ${modRoot}`);
      continue;
    }
    const families = await loadModCatalog(modRoot, config);
    const unitFamily = families.Unit || new Map();
    const weaponFamily = families.Weapon || new Map();
    const effectFamily = families.Effect || new Map();
    const units = [];
    for (const [id, uEntry] of unitFamily.entries()) {
      if (isAuxiliaryId(id, config.auxiliaryIdSuffixes)) continue;
      const u = extractUnitMetrics(uEntry, weaponFamily, effectFamily, weights);
      if (!u) continue;
      if (shouldSkipUnit(u, weights)) continue;
      u.commander = mod.id;
      u.commander_race = mod.race;
      units.push(u);
    }
    console.log(`[balance] ${mod.id}: ${units.length} units (total entries: ${unitFamily.size})`);
    alengerUnitsByCommander.push({ commander: mod.id, modRoot, units });
  }

  // === 加载官方 mod ===
  // 官方 mod 的单位 ID 不带指挥官前缀（如 "Barracks"、"Marine"），
  // 无法按 ID 前缀准确归类到具体指挥官。改为：合并所有官方战斗单位作为基准池。
  // 这符合"基准锚定"的统计目标 —— 用 SC2 整体单位分布作为基线。
  console.log("[balance] === 加载官方 mod（基准池，不按指挥官过滤）===");
  const officialUnits = [];
  for (const mod of config.officialMods) {
    const modRoot = resolve(workspaceRoot, mod.path.replace(/\//g, sep));
    if (!existsSync(modRoot)) {
      console.warn(`[balance] official mod missing: ${mod.id} -> ${modRoot}`);
      continue;
    }
    const families = await loadModCatalog(modRoot, config);
    const unitFamily = families.Unit || new Map();
    const weaponFamily = families.Weapon || new Map();
    const effectFamily = families.Effect || new Map();
    let modCount = 0;
    for (const [id, uEntry] of unitFamily.entries()) {
      // 官方 mod 同样应用辅助 ID 过滤，排除明显非战斗单位
      if (isAuxiliaryId(id, config.auxiliaryIdSuffixes)) continue;
      const u = extractUnitMetrics(uEntry, weaponFamily, effectFamily, weights);
      if (!u) continue;
      if (shouldSkipUnit(u, weights)) continue;
      u.commander = "OfficialBaseline";
      u.commander_race = u.race;
      u.source_mod = mod.id;
      officialUnits.push(u);
      modCount++;
    }
    console.log(`[balance] official ${mod.id}: ${modCount} units (total entries: ${unitFamily.size})`);
  }
  console.log(`[balance] 官方基准池单位数: ${officialUnits.length}`);

  // 起义单位展开
  const alengerUnits = alengerUnitsByCommander.flatMap((x) => x.units);
  const allUnits = [...alengerUnits, ...officialUnits];
  console.log(`[balance] 起义单位数: ${alengerUnits.length}`);
  console.log(`[balance] 全部单位数: ${allUnits.length}`);

  // === 评分 ===
  console.log("[balance] === 评分 ===");
  const scoredAlenger = alengerUnits.map((u) => ({ ...u, ...scoreUnit(u, weights) }));
  const scoredOfficial = officialUnits.map((u) => ({ ...u, ...scoreUnit(u, weights) }));

  // 起义 + 官方一起分组（用于内部 z）
  const allScored = [...scoredAlenger, ...scoredOfficial];
  const { enriched, groupStats: groupStatsAll } = computeGroupStatistics(allScored, weights);

  // 官方基准（仅官方单位单独分组）
  const officialEnrichedResult = computeGroupStatistics(scoredOfficial, weights);
  const groupStatsOfficial = officialEnrichedResult.groupStats;
  const enrichedOfficial = officialEnrichedResult.enriched;

  // 起义单独分组（用于报告对照）
  const alengerEnrichedResult = computeGroupStatistics(scoredAlenger, weights);
  const groupStatsAlenger = alengerEnrichedResult.groupStats;
  const enrichedAlenger = alengerEnrichedResult.enriched;

  // 计算 z-scores：起义 vs 官方合并组的统计 vs 官方单独统计
  const zAnalyzed = computeZScores(enriched, groupStatsAll, groupStatsOfficial);
  const alengerZAnalyzed = zAnalyzed.filter((u) => u.commander && u.commander.startsWith("Alenger"));

  // Δ_global：起义 S 均值 - 官方 S 均值
  const alengerS = enrichedAlenger.map((u) => u.S).filter((v) => isFinite(v) && v > 0);
  const officialS = enrichedOfficial.map((u) => u.S).filter((v) => isFinite(v) && v > 0);
  const muAlenger = alengerS.length ? alengerS.reduce((a, b) => a + b, 0) / alengerS.length : 0;
  const muOfficial = officialS.length ? officialS.reduce((a, b) => a + b, 0) / officialS.length : 0;
  const deltaGlobal = muAlenger - muOfficial;

  // === 离群 ===
  const outliers = findOutliers(alengerZAnalyzed, weights);
  console.log(`[balance] 离群单位数: ${outliers.length}`);

  // === 补丁建议 ===
  const patches = suggestPatches(outliers, weights);

  // === 克制矩阵 ===
  console.log("[balance] === 计算克制矩阵 ===");
  const counterMatrix = computeCounterMatrix(enrichedAlenger, weights);
  console.log(`[balance] 克制对数: ${counterMatrix.per_attacker.length}`);

  // === 写报告 ===
  console.log("[balance] === 写报告 ===");
  await mkdir(OUTPUT_DIR, { recursive: true });
  await reporter.writeUnitsRaw(alengerUnits, OUTPUT_DIR);
  await reporter.writeUnitsScored(alengerZAnalyzed, OUTPUT_DIR);
  await reporter.writeOutliers(outliers, OUTPUT_DIR);
  await reporter.writeBaselineOfficial(groupStatsOfficial, officialUnits.length, OUTPUT_DIR);
  await reporter.writeCounterMatrix(counterMatrix, OUTPUT_DIR);
  await reporter.writePatchSuggestions(patches, OUTPUT_DIR);
  await reporter.writeFormulaWeights(weights, OUTPUT_DIR);
  await reporter.writeReportMarkdown({
    outputDir: OUTPUT_DIR,
    alengerUnitCount: alengerUnits.length,
    officialUnitCount: officialUnits.length,
    totalUnits: allUnits.length,
    groupStatsAlenger,
    groupStatsOfficial,
    deltaGlobal,
    outliers,
    counterMatrix,
    patches,
    weights
  });

  console.log("[balance] === 完成 ===");
  console.log(`[balance] 起义单位数: ${alengerUnits.length}`);
  console.log(`[balance] 官方单位数: ${officialUnits.length}`);
  console.log(`[balance] 离群单位数: ${outliers.length}`);
  console.log(`[balance] Top 5 离群单位:`);
  outliers.slice(0, 5).forEach((o, i) => {
    console.log(`  ${i + 1}. ${o.id} (${o.commander}) z_internal=${o.z_internal.toFixed(2)} z_official=${o.z_official.toFixed(2)}`);
  });
  console.log(`[balance] 报告目录: ${OUTPUT_DIR}`);
}

// 子命令：extract --commander X
async function runExtract(commander) {
  const config = JSON.parse(await readFile(join(balanceRoot, "config", "commanders.json"), "utf8"));
  const weights = JSON.parse(await readFile(join(balanceRoot, "config", "formula-weights.json"), "utf8"));
  const mod = config.alengerMods.find((m) => m.id === commander);
  if (!mod) throw new Error(`Unknown commander: ${commander}`);
  const modRoot = resolve(workspaceRoot, mod.path.replace(/\//g, sep));
  const families = await loadModCatalog(modRoot, config);
  const unitFamily = families.Unit || new Map();
  const weaponFamily = families.Weapon || new Map();
  const effectFamily = families.Effect || new Map();
  const units = [];
  for (const [id, uEntry] of unitFamily.entries()) {
    if (isAuxiliaryId(id, config.auxiliaryIdSuffixes)) continue;
    const u = extractUnitMetrics(uEntry, weaponFamily, effectFamily, weights);
    if (!u) continue;
    if (shouldSkipUnit(u, weights)) continue;
    u.commander = mod.id;
    units.push(u);
  }
  console.log(JSON.stringify({ commander, count: units.length, units }, null, 2));
}

// CLI 路由
const [cmd, ...rest] = process.argv.slice(2);
try {
  if (cmd === "analyze") {
    const flag = rest[0];
    if (flag !== "--all") {
      console.error("Usage: node tools/balance/src/index.mjs analyze --all");
      process.exit(1);
    }
    await runAnalyzeAll();
  } else if (cmd === "extract") {
    const cmdrFlag = rest[0];
    if (cmdrFlag !== "--commander") {
      console.error("Usage: node tools/balance/src/index.mjs extract --commander <name>");
      process.exit(1);
    }
    await runExtract(rest[1]);
  } else {
    console.error("Unknown command. Available: analyze --all | extract --commander <name>");
    process.exit(1);
  }
} catch (err) {
  console.error("[balance] FATAL:", err);
  console.error(err.stack);
  process.exit(1);
}
