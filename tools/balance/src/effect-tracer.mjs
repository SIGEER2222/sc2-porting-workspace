// src/effect-tracer.mjs
// 从 Weapon.Effect 出发，深度优先搜索 Effect 链直到 CEffectDamage。
// 最多 8 层，识别环。
//
// 支持的 Effect 类型：
//   CEffectDamage       -> 终态，返回 Amount / AttributeBonus / Kind
//   CEffectSet          -> EffectArray[] 递归
//   CEffectSearch       -> AreaArray[].Effect 递归；记录 AreaArray.Radius 作为 AoE 半径
//   CEffectEnumArea     -> 同 CEffectSearch（新版命名）
//   CEffectLaunchMissile-> ImpactEffect 递归（也支持 Effect 字段）
//   CEffectApplyBehavior / CEffectCreateUnit / CEffectIssueOrder -> 终态，无伤害
//   CEffectCreatePersistent -> 取 InitialEffect / FinalEffect / PeriodicEffectArray[]，递归
//
// 返回 traceEffectChain 返回 { damages: [{amount, bonus, kind}], max_radius }

const MAX_DEPTH = 8;

// DamageLeaf: { amount: number, bonus: {armor_type -> number}, kind: string|null }
// 我们用 plain object 表示。

/**
 * 追踪 effect 链
 * @param {string} effectId  起始 effect ID
 * @param {Map<string, Entry>} effectFamily  Effect family 的所有 entries
 * @returns {{ damages: Array<{amount:number, bonus:Object, kind:string|null}>, max_radius: number, trace_log: string[] }}
 */
export function traceEffectChain(effectId, effectFamily) {
  const ctx = {
    effectFamily,
    visited: new Set(),
    damages: [],
    maxRadius: 0,
    traceLog: []
  };
  _dfs(effectId, ctx, 0, []);
  return {
    damages: ctx.damages,
    max_radius: ctx.maxRadius,
    trace_log: ctx.traceLog
  };
}

function _dfs(effectId, ctx, depth, path) {
  if (!effectId) return;
  if (depth > MAX_DEPTH) {
    ctx.traceLog.push(`[depth-limit] ${effectId} (max ${MAX_DEPTH})`);
    return;
  }
  if (ctx.visited.has(effectId)) {
    ctx.traceLog.push(`[cycle] ${effectId}`);
    return;
  }
  ctx.visited.add(effectId);

  const entry = ctx.effectFamily.get(effectId);
  if (!entry) {
    ctx.traceLog.push(`[missing] ${effectId}`);
    return;
  }

  const ctype = entry.ctype;
  ctx.traceLog.push(`[visit:${depth}] ${ctype} ${effectId}`);

  switch (ctype) {
    case "CEffectDamage": {
      const amount = parseFloat(entry.fields.Amount) || 0;
      const kind = entry.fields.Kind || null;
      const bonus = {};
      const ab = entry.arrays.AttributeBonus || [];
      for (const item of ab) {
        if (item.index && item.value !== undefined) {
          bonus[item.index] = parseFloat(item.value) || 0;
        }
      }
      ctx.damages.push({ amount, bonus, kind });
      return;
    }

    case "CEffectSet":
    case "CEffectSetCopy": {
      // EffectArray value 指向子效果
      const arr = entry.arrays.EffectArray || [];
      for (const item of arr) {
        const childId = item.value;
        if (childId) _dfs(childId, ctx, depth + 1, [...path, effectId]);
      }
      return;
    }

    case "CEffectSearch":
    case "CEffectEnumArea": {
      // AreaArray 上有 Radius 和 Effect
      const arr = entry.arrays.AreaArray || [];
      for (const item of arr) {
        const radius = parseFloat(item.Radius) || 0;
        if (radius > ctx.maxRadius) ctx.maxRadius = radius;
        const childId = item.Effect;
        if (childId) _dfs(childId, ctx, depth + 1, [...path, effectId]);
      }
      // 也可能有 Effect 字段（直接指向）
      const directChild = entry.fields.Effect;
      if (directChild) _dfs(directChild, ctx, depth + 1, [...path, effectId]);
      return;
    }

    case "CEffectLaunchMissile": {
      // ImpactEffect 字段
      const impactId = entry.fields.ImpactEffect;
      if (impactId) _dfs(impactId, ctx, depth + 1, [...path, effectId]);
      // 部分变体可能用 Effect 字段
      const altChild = entry.fields.Effect;
      if (altChild && altChild !== impactId) _dfs(altChild, ctx, depth + 1, [...path, effectId]);
      return;
    }

    case "CEffectCreatePersistent":
    case "CEffectCreatePersistentEffect": {
      const initial = entry.fields.InitialEffect;
      if (initial) _dfs(initial, ctx, depth + 1, [...path, effectId]);
      const final = entry.fields.FinalEffect || entry.fields.ExpireEffect;
      if (final) _dfs(final, ctx, depth + 1, [...path, effectId]);
      const periodicArr = entry.arrays.PeriodicEffectArray || [];
      for (const item of periodicArr) {
        const childId = item.value;
        if (childId) _dfs(childId, ctx, depth + 1, [...path, effectId]);
      }
      return;
    }

    case "CEffectApplyBehavior":
    case "CEffectApplyTimedLife":
    case "CEffectCreateUnit":
    case "CEffectCreateHealer":
    case "CEffectIssueOrder":
    case "CEffectGrantXP":
    case "CEffectRemoveBehavior":
    case "CEffectDestroy":
    case "CEffectModifyPlayer":
    case "CEffectModifyUnit":
    case "CEffectSet":
    case "CEffectSendTransmission":
      // 终态：无伤害
      return;

    default:
      // 未识别的 Effect 类型：尝试通用字段 Effect / ImpactEffect / EffectArray
      {
        const fallbackChild = entry.fields.Effect || entry.fields.ImpactEffect;
        if (fallbackChild) _dfs(fallbackChild, ctx, depth + 1, [...path, effectId]);
        const arr = entry.arrays.EffectArray || [];
        for (const item of arr) {
          const childId = item.value;
          if (childId) _dfs(childId, ctx, depth + 1, [...path, effectId]);
        }
        return;
      }
  }
}

/**
 * 计算一个武器效果链的总伤害叶子列表 + AoE 半径
 * @returns {{ damages: Array, max_radius: number }}
 */
export function traceWeaponEffects(weaponEntry, effectFamily) {
  const rootEffectId = weaponEntry.fields.Effect || weaponEntry.fields.DisplayEffect;
  if (!rootEffectId) {
    return { damages: [], max_radius: 0 };
  }
  return traceEffectChain(rootEffectId, effectFamily);
}
