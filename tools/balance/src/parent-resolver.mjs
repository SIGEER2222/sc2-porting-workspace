// src/parent-resolver.mjs
// 递归合并 parent 继承链，子覆盖父。
// SC2 catalog 标准继承语义：
//   - 单值字段：子覆盖父（子未指定则继承父的值）
//   - 数组字段：默认子追加到父的数组末尾；若子数组元素含 removed="1"，则按 index 移除父对应项
//   - 没有循环引用检测：依赖 parent 链无环。若出现环，通过 visited 集合切断。

const VISITED_LIMIT = 32; // 防止极端深度爆栈

/**
 * 解析单个 entry 的完整继承链，返回一个合并后的 entry。
 * @param {Map<string, Map<string, Entry>>} allFamilies  family -> (id -> Entry)
 * @param {Entry} entry
 * @param {Map<string, Entry>} memo  缓存已解析的 entry（按 family:id 索引）
 */
export function resolveWithParent(entry, allFamilies, memo = new Map()) {
  const cacheKey = `${entry.family}::${entry.id}`;
  if (memo.has(cacheKey)) return memo.get(cacheKey);

  // 防止循环引用
  const visiting = new Set();
  const stack = []; // 从根到当前 entry 的顺序
  collectChain(entry, allFamilies, visiting, stack, 0);

  // 从根（最早的祖先）开始向下合并
  let merged = {
    family: entry.family,
    ctype: entry.ctype,
    id: entry.id,
    parent: entry.parent,
    attrs: {},
    fields: {},
    arrays: {},
    sourceUri: entry.sourceUri
  };

  for (const ancestor of stack) {
    mergeInto(merged, ancestor);
  }
  // 最后确保 id 是当前 entry 的 id（防止被祖先覆盖）
  merged.id = entry.id;
  merged.parent = entry.parent;

  memo.set(cacheKey, merged);
  return merged;
}

function collectChain(entry, allFamilies, visiting, stack, depth) {
  if (!entry) return;
  if (depth > VISITED_LIMIT) return;
  const cacheKey = `${entry.family}::${entry.id}`;
  if (visiting.has(cacheKey)) return; // 环检测
  visiting.add(cacheKey);

  // 递归父级
  if (entry.parent) {
    const parentEntry = lookupEntry(allFamilies, entry.family, entry.parent);
    if (parentEntry) {
      collectChain(parentEntry, allFamilies, visiting, stack, depth + 1);
    }
  }

  // 自身入栈（在父之后，使 stack 顺序为根->叶）
  stack.push(entry);
  visiting.delete(cacheKey);
}

function lookupEntry(allFamilies, family, id) {
  const fam = allFamilies[family];
  if (!fam) return null;
  return fam.get(id) || null;
}

// 将 ancestor 的字段合并进 merged。
// - fields：后写覆盖
// - arrays：先复制父的，再追加子的；若子元素有 removed="1"，按 index 移除父对应项
function mergeInto(merged, ancestor) {
  // 拷贝 attrs（子覆盖父）
  for (const [k, v] of Object.entries(ancestor.attrs || {})) {
    if (k === "id" || k === "parent") continue;
    merged.attrs[k] = v;
  }

  // 拷贝 fields
  for (const [k, v] of Object.entries(ancestor.fields || {})) {
    merged.fields[k] = v;
  }

  // 拷贝 arrays（按字段名分组）
  for (const [name, childArr] of Object.entries(ancestor.arrays || {})) {
    if (!merged.arrays[name]) merged.arrays[name] = [];
    // 处理 removed="1"
    for (const item of childArr) {
      if (item.removed === "1" && "index" in item) {
        // 移除父级同 index 的项
        merged.arrays[name] = merged.arrays[name].filter(
          (x) => !(x.index === item.index)
        );
      } else {
        merged.arrays[name].push(item);
      }
    }
  }
}

// 批量解析：传入 Map<family, Map<id, Entry>>，返回 Map<family, Map<id, Entry>>（已合并 parent）
export function resolveAll(allFamilies) {
  const memo = new Map();
  const result = {};
  for (const family of Object.keys(allFamilies)) {
    const familyMap = allFamilies[family];
    if (!familyMap) continue;
    result[family] = new Map();
    for (const [id, entry] of familyMap.entries()) {
      const resolved = resolveWithParent(entry, allFamilies, memo);
      result[family].set(id, resolved);
    }
  }
  return result;
}
