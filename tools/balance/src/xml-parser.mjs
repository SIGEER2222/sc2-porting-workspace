// src/xml-parser.mjs
// 行级正则解析 SC2 catalog XML。不依赖任何外部包。
//
// 支持的元素结构：
//   <CTag id="X" parent="Y">  ... </CTag>      块级元素
//   <Field value="v"/>                         单值字段
//   <FieldArray index="K" value="V"/>          带索引的数组元素
//   <FieldArray Link="..."/>                   链接型数组元素
//   <Container> ... </Container>                容器，开标签属性也被记录
//
// 解析结果：Entry[]
//   Entry = {
//     family,    // 'Unit' | 'Weapon' | 'Effect' | 'Abil' | 'Behavior' | ...
//     ctype,     // 'CUnit' | 'CWeaponLegacy' | 'CEffectDamage' | ...
//     id, parent,
//     attrs,     // 开标签上的所有属性
//     fields,    // { fieldName: value (字符串) }  —— 后写覆盖前写
//     arrays,    // { fieldName: Array<{index?, value?, Link?, ...}> }
//     sourceUri  // 文件相对路径
//   }

import { basename } from "node:path";

// SC2 catalog 家族名到内部 family 别名的映射（与 analyze-catalog.mjs 风格对齐）。
const FAMILY_BY_CTYPE_PREFIX = {
  CUnit: "Unit",
  CWeapon: "Weapon",
  CEffect: "Effect",
  CAbil: "Abil",
  CBehavior: "Behavior",
  CActor: "Actor",
  CButton: "Button",
  CModel: "Model",
  CMover: "Mover",
  CRace: "Race",
  CRequirement: "Requirement",
  CTurret: "Turret",
  CUpgrade: "Upgrade",
  CValidator: "Validator",
  CTargetFind: "TargetFind",
  CTargetSort: "TargetSort",
  CFootprint: "Footprint",
  CTactical: "Tactical"
};

// 给定 <CXXXX id="..."> 标签，根据前缀匹配出 family。
function detectFamily(ctype) {
  // 优先完整匹配
  if (FAMILY_BY_CTYPE_PREFIX[ctype]) return FAMILY_BY_CTYPE_PREFIX[ctype];
  // 回退：按前缀
  for (const prefix of Object.keys(FAMILY_BY_CTYPE_PREFIX)) {
    if (ctype.startsWith(prefix)) return FAMILY_BY_CTYPE_PREFIX[prefix];
  }
  return null;
}

// 解析属性字符串 "id=\"X\" parent=\"Y\"" -> { id: "X", parent: "Y" }
function parseAttrs(attrStr) {
  const attrs = {};
  if (!attrStr) return attrs;
  const re = /([\w-]+)\s*=\s*"([^"]*)"/g;
  let m;
  while ((m = re.exec(attrStr)) !== null) {
    attrs[m[1]] = m[2];
  }
  return attrs;
}

// 判定字段名是否本质上是数组（含 Array 后缀，或属于已知的列表字段）
// 注意：以下字段是单值字段（不应在此列表中）：
//   Race, Buildable, Button, InfoCard, EditorSuffix, Product, GlossaryCategory, GlossaryPriority
//   Effect, ImpactEffect, InitialEffect, FinalEffect, DisplayEffect, Mover, LeaderAlias 等
const KNOWN_ARRAY_FIELDS = new Set([
  "WeaponArray",
  "BehaviorArray",
  "AbilArray",
  "Attributes",
  "PlaneArray",
  "CostResource",
  "FlagArray",
  "EffectArray",
  "AreaArray",
  "AttributeBonus",
  "CardLayouts",
  "ProductArray",
  "SortArray",
  "ValidatorArray",
  "RequirementArray",
  "MatchFlags",
  "AccumulatorArray",
  "PeriodicEffectArray",
  "PeriodicOffsetArray",
  "PeriodicPeriodArray",
  "TurretArray",
  "UnitArray",
  "DamageArray",
  "DeathArray",
  "SoundArray",
  "ModelArray",
  "TechAlias",
  "ExcludeRaceAlias",
  "Hangar",
  "HangarQueue",
  "ResourceDataArray",
  "LayoutButtons",
  "Collide"
]);

function isArrayField(name, attrs) {
  if (KNOWN_ARRAY_FIELDS.has(name)) return true;
  if (name.endsWith("Array")) return true;
  // 携带 index 或 Link 的也算数组
  if ("index" in attrs) return true;
  if ("Link" in attrs) return true;
  return false;
}

function addChildEntry(entry, name, attrs) {
  if (isArrayField(name, attrs)) {
    if (!entry.arrays[name]) entry.arrays[name] = [];
    entry.arrays[name].push(attrs);
  } else if ("value" in attrs) {
    // 单值字段：后写覆盖前写（与 SC2 catalog 行为一致）
    entry.fields[name] = attrs.value;
  } else {
    // 容器型字段（如 Marker、CardLayouts 内含子结构），保留开标签属性到 arrays 以便读取
    if (!entry.arrays[name]) entry.arrays[name] = [];
    entry.arrays[name].push(attrs);
  }
}

// 主解析函数
// content: 字符串 XML
// uri: 用于追溯的源标识
// 返回 Entry[]
export function parseCatalogXml(content, uri) {
  const entries = [];
  const lines = content.split(/\r?\n/);
  let current = null;
  let skipDepth = 0; // 当 > 0 时表示在多行容器内，要跳过其内部直到回到 0
  let inComment = false; // 跨行注释状态

  for (let i = 0; i < lines.length; i++) {
    let line = lines[i].trim();
    if (!line) continue;

    // 处理跨行注释状态
    if (inComment) {
      const endIdx = line.indexOf("-->");
      if (endIdx >= 0) {
        inComment = false;
        // 注释结束后的内容继续处理
        line = line.slice(endIdx + 3).trim();
        if (!line) continue;
      } else {
        continue;
      }
    }

    // 跳过 XML 声明
    if (line.startsWith("<?xml")) continue;
    if (line === "<Catalog>" || line === "</Catalog>") continue;

    // 处理注释开头 <!--
    // 可能是整行注释、跨行注释开始、或行内注释（含 --> 结束）
    if (line.startsWith("<!--")) {
      const endIdx = line.indexOf("-->", 4);
      if (endIdx >= 0) {
        // 同行注释结束，去掉注释部分继续处理剩余
        // 但 SC2 catalog 中注释行通常整行是注释，剩余为空
        const after = line.slice(endIdx + 3).trim();
        if (!after) continue;
        line = after; // 罕见情况：注释后有内容，继续处理
      } else {
        // 跨行注释开始
        inComment = true;
        continue;
      }
    }

    // 跳过行中间残留的注释结束符（如 <X/-->）
    // 这种行是注释内部的伪标签，应整体跳过
    if (line.includes("-->")) {
      continue;
    }

    if (skipDepth > 0) {
      // 处于多行容器内部
      // 计算开/闭标签的净深度变化
      const opens = (line.match(/<[A-Za-z0-9]+(\s+[^>]*?)?[^/]>/g) || []).length;
      const closes = (line.match(/<\/[A-Za-z0-9]+>/g) || []).length;
      skipDepth += opens - closes;
      if (skipDepth < 0) skipDepth = 0;
      continue;
    }

    // 顶层元素开始：<CTag ...> 或 <CTag .../>
    if (!current) {
      const startMatch = line.match(/^<(C[A-Za-z0-9]+)(\s+[^>]*?)?\/?>/);
      if (!startMatch) continue;
      const ctype = startMatch[1];
      const attrStr = (startMatch[2] || "").trim();
      const attrs = parseAttrs(attrStr);
      const id = attrs.id;
      if (!id) continue;
      const family = detectFamily(ctype);
      if (!family) continue;

      const isSelfClosing = line.endsWith("/>");
      current = {
        family,
        ctype,
        id,
        parent: attrs.parent || null,
        attrs,
        fields: {},
        arrays: {},
        sourceUri: uri
      };

      if (isSelfClosing) {
        entries.push(current);
        current = null;
      }
      continue;
    }

    // 顶层元素的闭合
    const closeMatch = line.match(/^<\/(C[A-Za-z0-9]+)>$/);
    if (closeMatch) {
      entries.push(current);
      current = null;
      continue;
    }

    // 子元素
    const childMatch = line.match(/^<([A-Za-z0-9]+)(\s+[^>]*?)?\/?>/);
    if (childMatch) {
      const name = childMatch[1];
      const attrStr = (childMatch[2] || "").trim();
      const attrs = parseAttrs(attrStr);
      const isSelfClosing = line.endsWith("/>");
      addChildEntry(current, name, attrs);
      if (!isSelfClosing) {
        // 多行容器：进入跳过模式
        // 注意：当前行可能本身也包含开+闭标签，需要判断
        const sameLineClose = line.includes(`</${name}>`);
        if (!sameLineClose) {
          skipDepth = 1;
        }
      }
      continue;
    }
  }

  // 兜底：若 XML 不规范，最后一个 entry 未 push
  if (current) entries.push(current);
  return entries;
}

// 加载一个 mod 目录下的所有 catalog XML，按 family 分类返回。
// gameDataDir: 绝对路径
// fileNames: 例如 ['UnitData.xml', 'WeaponData.xml', ...]
// 返回 { family -> Map<id, Entry> }
export async function loadCatalogFiles(gameDataDir, fileNames, readFileFn) {
  const families = {};
  for (const fn of fileNames) {
    const fullPath = `${gameDataDir}/${fn}`;
    let content;
    try {
      content = await readFileFn(fullPath);
    } catch (err) {
      // 文件缺失：跳过
      continue;
    }
    const uri = fn; // 简化：仅文件名
    const entries = parseCatalogXml(content, uri);
    for (const entry of entries) {
      if (!families[entry.family]) families[entry.family] = new Map();
      // 后写覆盖（同一文件内 ID 重复时）
      families[entry.family].set(entry.id, entry);
    }
  }
  return families;
}

// 工具：判断 entry 是否有特定属性（Attributes/FlagArray/PlaneArray）
export function hasAttribute(entry, attributeName, family = "Attributes") {
  const arr = entry.arrays[family];
  if (!arr) return false;
  return arr.some((a) => a.index === attributeName && a.value === "1");
}

// 工具：取数组中第一个匹配 index 的 value
export function getArrayValue(entry, family, attributeName) {
  const arr = entry.arrays[family];
  if (!arr) return null;
  const found = arr.find((a) => a.index === attributeName);
  return found ? found.value : null;
}

// 工具：取数组中所有匹配 index 的 value
export function getArrayValues(entry, family, attributeName) {
  const arr = entry.arrays[family];
  if (!arr) return [];
  return arr.filter((a) => a.index === attributeName).map((a) => a.value);
}

// 工具：取数组中所有 Link 字段
export function getArrayLinks(entry, family) {
  const arr = entry.arrays[family];
  if (!arr) return [];
  return arr.map((a) => a.Link).filter((x) => x);
}

// 文件名 -> family 映射（用于结果分类）
export const FILE_FAMILY_HINT = {
  UnitData: "Unit",
  WeaponData: "Weapon",
  EffectData: "Effect",
  AbilData: "Abil",
  BehaviorData: "Behavior"
};
