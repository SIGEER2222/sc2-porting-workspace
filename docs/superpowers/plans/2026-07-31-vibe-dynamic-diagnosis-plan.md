# Vibe 动态诊断 MVP 实施计划（Stage 1）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 扩展 Vibe Kernel 支持升级解锁/科技树查询/单位属性查询/单位 tag 列表，新增诊断脚本跑通"reset → set_level → spawn → query_tags → query_attrs → assert"闭环，在 vibe 测试地图上验证 Marine + ShieldWall 升级诊断。

**Architecture:** 复用现有 Bank RPC 三层结构（request/response/index）与 BankPoll 触发器。Galaxy 侧在 `libVibeKernel_gf_Dispatch` 注册 4 个新 handler；Python 侧新增 `vibe-diagnose.py` 诊断脚本调用 `VibeHost.request` 跑期望值表，输出 PASS/FAIL 报告。

**Tech Stack:** Galaxy（SC2 触发器脚本）、Python 3（aiohttp + VibeHost）、JSON（whitelist/期望值表/报告）。

**设计文档:** [docs/superpowers/specs/2026-07-31-vibe-dynamic-diagnosis-design.md](file:///e:/Code/MyMod/SC2VibeTools/sc2-porting-workspace/docs/superpowers/specs/2026-07-31-vibe-dynamic-diagnosis-design.md)

**设计细化（相对 spec）:**
- 新增第 4 个 handler `query.unit_tags`（辅助）：spec 的 3 个诊断 handler 依赖 unit_tag，但现有 `unit.spawn`/`query.units` payload 都不含 unit_tag，诊断脚本无法拿到 spawned unit 的 tag。`query.unit_tags` 返回 player+unit_type 的 tag 列表，填补 `query.units`（只 count）与 `query.unit`（单 tag 详情）之间的缺口。
- `query.unit_attrs` MVP 只返回稳定字段：`unit_type/life/max_life/armor/shield/energy`。`weapon_damage/weapon_range/attributes` 在 MVP 标 `"unavailable"`（Catalog 路径复杂，按 spec 风险缓解策略延后）。marine-baseline 只 assert armor，不需 weapon。

---

## 文件结构

| 文件 | 操作 | 责任 |
|---|---|---|
| `tools/galaxy-vibe/kernel/whitelist.json` | 修改 | 注册 4 个新 operation 的 args/payload_schema |
| `tools/galaxy-vibe/kernel/LibVibeKernel.galaxy` | 修改 | 新增 4 个 handler + Dispatch 分发 |
| `tools/galaxy-vibe/host/vibe_host.py` | 修改 | 加 4 个便捷方法（upgrade_set_level/tech_tree_check/query_unit_tags/query_unit_attrs） |
| `tools/galaxy-vibe/tests/test_kernel.py` | 修改 | 扩展 whitelist 契约测试 |
| `tools/galaxy-vibe/diagnose/vibe-diagnose.py` | 新建 | 诊断脚本：跑期望值表 → 输出报告 |
| `tools/galaxy-vibe/diagnose/expectations/marine-baseline.json` | 新建 | Marine + ShieldWall 期望值表 |
| `artifacts/vibe-diagnose/<timestamp>/report.json` | 生成 | 真机运行产物 |
| `artifacts/vibe-diagnose/<timestamp>/report.md` | 生成 | 真机运行产物 |

---

## Task 1: whitelist.json 注册 4 个新 operation

**Files:**
- Modify: `tools/galaxy-vibe/kernel/whitelist.json`
- Test: `tools/galaxy-vibe/tests/test_kernel.py`（`TestWhitelist.test_mvp_operations_present`）

- [ ] **Step 1: 写失败测试 — 扩展 test_mvp_operations_present 加 4 个新 op**

打开 `tools/galaxy-vibe/tests/test_kernel.py`，找到 `TestWhitelist.test_mvp_operations_present`（约 148 行）。当前断言的 MVP 操作列表后追加 4 个新操作。修改后的测试：

```python
    def test_mvp_operations_present(self):
        """MVP 必须存在的操作。"""
        required = [
            "system.ping",
            "scenario.reset",
            "unit.spawn",
            "unit.kill",
            "unit.set_vital",
            "player.set_resource",
            "query.units",
            "query.unit",
            "query.mission",
            "visual.actor_tint",
            "visual.actor_scale",
            "visual.actor_opacity",
            # Stage 1 新增：动态诊断
            "upgrade.set_level",
            "tech_tree.check",
            "query.unit_tags",
            "query.unit_attrs",
        ]
        for op in required:
            self.assertIn(op, self.whitelist["operations"], f"缺少 MVP 操作: {op}")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python tools/galaxy-vibe/tests/test_kernel.py TestWhitelist.test_mvp_operations_present`
Expected: FAIL，报 `AssertionError: 缺少 MVP 操作: upgrade.set_level`

- [ ] **Step 3: 改 whitelist.json — 在 operations 对象末尾加 4 个条目**

在 `tools/galaxy-vibe/kernel/whitelist.json` 的 `"operations"` 对象内，`"visual.actor_opacity"` 条目之后（`}` 后加逗号）追加：

```json
    "upgrade.set_level": {
      "category": "upgrade",
      "produces_side_effect": true,
      "args": {
        "player": {"type": "integer", "required": true, "min": 1, "max": 15},
        "upgrade": {"type": "string", "required": true, "pattern": "^[A-Za-z][A-Za-z0-9_]*$"},
        "level": {"type": "integer", "required": true, "min": 0, "max": 15}
      },
      "payload_schema": {
        "applied": "integer",
        "player": "integer",
        "upgrade": "string",
        "level": "integer"
      }
    },
    "tech_tree.check": {
      "category": "tech_tree",
      "produces_side_effect": false,
      "args": {
        "player": {"type": "integer", "required": true, "min": 1, "max": 15},
        "upgrade": {"type": "string", "required": true, "pattern": "^[A-Za-z][A-Za-z0-9_]*$"}
      },
      "payload_schema": {
        "count": "integer",
        "unlocked": "integer",
        "upgrade": "string",
        "player": "integer"
      }
    },
    "query.unit_tags": {
      "category": "query",
      "produces_side_effect": false,
      "args": {
        "player": {"type": "integer", "required": false, "min": 0, "max": 15, "default": 0},
        "unit_type": {"type": "string", "required": false, "default": ""}
      },
      "payload_schema": {
        "count": "integer",
        "tags": "array",
        "unit_type": "string",
        "player": "integer"
      }
    },
    "query.unit_attrs": {
      "category": "query",
      "produces_side_effect": false,
      "args": {
        "unit_tag": {"type": "integer", "required": true}
      },
      "payload_schema": {
        "unit_tag": "integer",
        "unit_type": "string",
        "life": "fixed",
        "max_life": "fixed",
        "shields": "fixed",
        "energy": "fixed",
        "armor": "fixed",
        "weapon_damage": "string",
        "weapon_range": "string",
        "attributes": "string"
      }
    }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python tools/galaxy-vibe/tests/test_kernel.py TestWhitelist`
Expected: PASS（所有 TestWhitelist 用例通过）

- [ ] **Step 5: 提交**

```bash
git add tools/galaxy-vibe/kernel/whitelist.json tools/galaxy-vibe/tests/test_kernel.py
git commit -m "feat(vibe): whitelist 注册 upgrade.set_level/tech_tree.check/query.unit_tags/query.unit_attrs"
```

---

## Task 2: Kernel 实现 upgrade.set_level handler

**Files:**
- Modify: `tools/galaxy-vibe/kernel/LibVibeKernel.galaxy`（在 `HandleVisualActorOpacity` 之后、`gf_Dispatch` 之前插入）
- Test: `tools/galaxy-vibe/tests/test_kernel.py`（`TestGalaxyStaticCheck`）

- [ ] **Step 1: 写 Galaxy 静态检查占位（已有 test_kernel_galaxy_no_syntax_errors，无需新增）**

`TestGalaxyStaticCheck.test_kernel_galaxy_no_syntax_errors`（约 416 行）已对整个 LibVibeKernel.galaxy 做静态检查。新增 handler 后该测试会自动覆盖。确认该测试存在即可，无需修改。

- [ ] **Step 2: 实现 handler — 在 HandleVisualActorOpacity 函数之后插入**

在 `tools/galaxy-vibe/kernel/LibVibeKernel.galaxy` 中，找到 `libVibeKernel_gf_HandleVisualActorOpacity` 函数的结束 `}`（约 494 行），在其后、`// ---- 主分发器 ----` 注释之前插入：

```galaxy
string libVibeKernel_gf_HandleUpgradeSetLevel(string argsJson) {
    int player;
    string upgrade;
    int level;
    string payload;
    player = libVibeKernel_gf_ArgsGetInt(argsJson, "player");
    upgrade = libVibeKernel_gf_ArgsGet(argsJson, "upgrade");
    level = libVibeKernel_gf_ArgsGetInt(argsJson, "level");

    if (player < 1 || player > 15) {
        return libVibeKernel_gf_MakeResponse("error", libVibeKernel_gv_currentSession, libVibeKernel_gv_lastRequestId, libVibeKernel_gv_lastSequence, "upgrade.set_level", "PLAYER_OUT_OF_RANGE", "{}");
    }
    if (level < 0 || level > 15) {
        return libVibeKernel_gf_MakeResponse("error", libVibeKernel_gv_currentSession, libVibeKernel_gv_lastRequestId, libVibeKernel_gv_lastSequence, "upgrade.set_level", "INVALID_LEVEL", "{}");
    }
    if (upgrade == "") {
        return libVibeKernel_gf_MakeResponse("error", libVibeKernel_gv_currentSession, libVibeKernel_gv_lastRequestId, libVibeKernel_gv_lastSequence, "upgrade.set_level", "INVALID_ARGS", "{}");
    }

    libNtve_gf_SetUpgradeLevelForPlayer(player, upgrade, level);
    libVibeKernel_gv_stateVersion += 1;
    payload = "{\"applied\":1,\"player\":" + IntToString(player) + ",\"upgrade\":\"" + upgrade + "\",\"level\":" + IntToString(level) + "}";
    return libVibeKernel_gf_MakeResponse("result", libVibeKernel_gv_currentSession, libVibeKernel_gv_lastRequestId, libVibeKernel_gv_lastSequence, "upgrade.set_level", "OK", payload);
}
```

- [ ] **Step 3: 跑 Galaxy 静态检查**

Run: `python tools/galaxy-vibe/tests/test_kernel.py TestGalaxyStaticCheck`
Expected: PASS（静态检查不报语法错误。注：Galaxy 无法离线执行，静态检查只验证语法/括号匹配）

- [ ] **Step 4: 提交**

```bash
git add tools/galaxy-vibe/kernel/LibVibeKernel.galaxy
git commit -m "feat(vibe): Kernel 新增 upgrade.set_level handler"
```

---

## Task 3: Kernel 实现 tech_tree.check handler

**Files:**
- Modify: `tools/galaxy-vibe/kernel/LibVibeKernel.galaxy`（在 `HandleUpgradeSetLevel` 之后插入）

- [ ] **Step 1: 实现 handler — 在 HandleUpgradeSetLevel 函数之后插入**

在 `libVibeKernel_gf_HandleUpgradeSetLevel` 函数 `}` 之后插入：

```galaxy
string libVibeKernel_gf_HandleTechTreeCheck(string argsJson) {
    int player;
    string upgrade;
    int count;
    int unlocked;
    string payload;
    player = libVibeKernel_gf_ArgsGetInt(argsJson, "player");
    upgrade = libVibeKernel_gf_ArgsGet(argsJson, "upgrade");

    if (player < 1 || player > 15) {
        return libVibeKernel_gf_MakeResponse("error", libVibeKernel_gv_currentSession, libVibeKernel_gv_lastRequestId, libVibeKernel_gv_lastSequence, "tech_tree.check", "PLAYER_OUT_OF_RANGE", "{}");
    }
    if (upgrade == "") {
        return libVibeKernel_gf_MakeResponse("error", libVibeKernel_gv_currentSession, libVibeKernel_gv_lastRequestId, libVibeKernel_gv_lastSequence, "tech_tree.check", "INVALID_ARGS", "{}");
    }

    count = TechTreeUpgradeCount(player, upgrade, c_techCountCompleteOnly);
    unlocked = 0;
    if (count > 0) { unlocked = 1; }
    // 查询不产生副作用，不递增 state_version
    payload = "{\"count\":" + IntToString(count) + ",\"unlocked\":" + IntToString(unlocked) + ",\"upgrade\":\"" + upgrade + "\",\"player\":" + IntToString(player) + "}";
    return libVibeKernel_gf_MakeResponse("result", libVibeKernel_gv_currentSession, libVibeKernel_gv_lastRequestId, libVibeKernel_gv_lastSequence, "tech_tree.check", "OK", payload);
}
```

- [ ] **Step 2: 跑 Galaxy 静态检查**

Run: `python tools/galaxy-vibe/tests/test_kernel.py TestGalaxyStaticCheck`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add tools/galaxy-vibe/kernel/LibVibeKernel.galaxy
git commit -m "feat(vibe): Kernel 新增 tech_tree.check handler"
```

---

## Task 4: Kernel 实现 query.unit_tags handler

**Files:**
- Modify: `tools/galaxy-vibe/kernel/LibVibeKernel.galaxy`（在 `HandleTechTreeCheck` 之后插入）

- [ ] **Step 1: 实现 handler — 在 HandleTechTreeCheck 函数之后插入**

```galaxy
string libVibeKernel_gf_HandleQueryUnitTags(string argsJson) {
    int player;
    string unitType;
    unitgroup lv_units;
    int count;
    int lv_i;
    unit lv_u;
    int lv_tag;
    string tags;
    string payload;
    player = libVibeKernel_gf_ArgsGetInt(argsJson, "player");
    unitType = libVibeKernel_gf_ArgsGet(argsJson, "unit_type");

    if (player < 0 || player > 15) {
        return libVibeKernel_gf_MakeResponse("error", libVibeKernel_gv_currentSession, libVibeKernel_gv_lastRequestId, libVibeKernel_gv_lastSequence, "query.unit_tags", "PLAYER_OUT_OF_RANGE", "{}");
    }

    lv_units = UnitGroup(unitType, player, RegionEntireMap(),
        UnitFilter(0, 0, 0, (1 << (c_targetFilterDead - 32)) | (1 << (c_targetFilterHidden - 32))), 0);
    count = UnitGroupCount(lv_units, c_unitCountAlive);
    tags = "[";
    for (lv_i = 1; lv_i <= count; lv_i += 1) {
        lv_u = UnitGroupUnit(lv_units, lv_i);
        if (lv_u != null) {
            lv_tag = UnitGetTag(lv_u);
            if (lv_i > 1) { tags = tags + ","; }
            tags = tags + IntToString(lv_tag);
        }
    }
    tags = tags + "]";
    // 查询不产生副作用，不递增 state_version
    payload = "{\"count\":" + IntToString(count) + ",\"tags\":" + tags + ",\"unit_type\":\"" + unitType + "\",\"player\":" + IntToString(player) + "}";
    return libVibeKernel_gf_MakeResponse("result", libVibeKernel_gv_currentSession, libVibeKernel_gv_lastRequestId, libVibeKernel_gv_lastSequence, "query.unit_tags", "OK", payload);
}
```

- [ ] **Step 2: 跑 Galaxy 静态检查**

Run: `python tools/galaxy-vibe/tests/test_kernel.py TestGalaxyStaticCheck`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add tools/galaxy-vibe/kernel/LibVibeKernel.galaxy
git commit -m "feat(vibe): Kernel 新增 query.unit_tags handler（返回 tag 列表）"
```

---

## Task 5: Kernel 实现 query.unit_attrs handler

**Files:**
- Modify: `tools/galaxy-vibe/kernel/LibVibeKernel.galaxy`（在 `HandleQueryUnitTags` 之后插入）

- [ ] **Step 1: 实现 handler — 在 HandleQueryUnitTags 函数之后插入**

MVP 只返回稳定字段（life/max_life/armor/shield/energy/unit_type），weapon/attributes 标 "unavailable"。

```galaxy
string libVibeKernel_gf_HandleQueryUnitAttrs(string argsJson) {
    int unitTag;
    unit lv_u;
    string typeName;
    fixed life;
    fixed maxLife;
    fixed shields;
    fixed energy;
    fixed armor;
    string payload;
    unitTag = libVibeKernel_gf_ArgsGetInt(argsJson, "unit_tag");
    lv_u = UnitFromId(unitTag);
    if (lv_u == null) {
        return libVibeKernel_gf_MakeResponse("error", libVibeKernel_gv_currentSession, libVibeKernel_gv_lastRequestId, libVibeKernel_gv_lastSequence, "query.unit_attrs", "UNIT_NOT_FOUND", "{}");
    }

    typeName = UnitGetType(lv_u);
    life = UnitGetPropertyFixed(lv_u, c_unitPropLife, true);
    maxLife = UnitGetPropertyFixed(lv_u, c_unitPropLifeMax, true);
    shields = UnitGetPropertyFixed(lv_u, c_unitPropShields, true);
    energy = UnitGetPropertyFixed(lv_u, c_unitPropEnergy, true);
    armor = UnitGetPropertyFixed(lv_u, c_unitPropArmor, true);
    // 查询不产生副作用，不递增 state_version
    // MVP: weapon_damage/weapon_range/attributes 标 unavailable（Catalog 路径复杂，延后）
    payload = "{\"unit_tag\":" + IntToString(unitTag) + ",\"unit_type\":\"" + typeName + "\",\"life\":" + FixedToString(life, 2) + ",\"max_life\":" + FixedToString(maxLife, 2) + ",\"shields\":" + FixedToString(shields, 2) + ",\"energy\":" + FixedToString(energy, 2) + ",\"armor\":" + FixedToString(armor, 2) + ",\"weapon_damage\":\"unavailable\",\"weapon_range\":\"unavailable\",\"attributes\":\"unavailable\"}";
    return libVibeKernel_gf_MakeResponse("result", libVibeKernel_gv_currentSession, libVibeKernel_gv_lastRequestId, libVibeKernel_gv_lastSequence, "query.unit_attrs", "OK", payload);
}
```

> 注：`c_unitPropLifeMax` 与 `c_unitPropArmor` 为 SC2 标准 unit property 常量。若 Galaxy 编译器报未声明，回退为 `c_unitPropLife`（max 用 life 近似）并删除 armor 行，仅返回 life/shields/energy。以真机编译结果为准。

- [ ] **Step 2: 跑 Galaxy 静态检查**

Run: `python tools/galaxy-vibe/tests/test_kernel.py TestGalaxyStaticCheck`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add tools/galaxy-vibe/kernel/LibVibeKernel.galaxy
git commit -m "feat(vibe): Kernel 新增 query.unit_attrs handler（MVP 稳定字段）"
```

---

## Task 6: Dispatch 注册 4 个新 operation

**Files:**
- Modify: `tools/galaxy-vibe/kernel/LibVibeKernel.galaxy`（`libVibeKernel_gf_Dispatch` 的白名单分发链，约 549-554 行之后）

- [ ] **Step 1: 在 Dispatch 分发链注册 4 个新 operation**

在 `libVibeKernel_gf_Dispatch` 中，找到 `visual.actor_opacity` 分支（约 553-554 行）：

```galaxy
    } else if (operation == "visual.actor_opacity") {
        result = libVibeKernel_gf_HandleVisualActorOpacity(args);
    } else {
```

在 `visual.actor_opacity` 分支之后、`else {` 之前插入 4 个新分支：

```galaxy
    } else if (operation == "visual.actor_opacity") {
        result = libVibeKernel_gf_HandleVisualActorOpacity(args);
    } else if (operation == "upgrade.set_level") {
        result = libVibeKernel_gf_HandleUpgradeSetLevel(args);
    } else if (operation == "tech_tree.check") {
        result = libVibeKernel_gf_HandleTechTreeCheck(args);
    } else if (operation == "query.unit_tags") {
        result = libVibeKernel_gf_HandleQueryUnitTags(args);
    } else if (operation == "query.unit_attrs") {
        result = libVibeKernel_gf_HandleQueryUnitAttrs(args);
    } else {
```

- [ ] **Step 2: 跑 Galaxy 静态检查 + 全量离线测试**

Run: `python tools/galaxy-vibe/tests/test_kernel.py`
Expected: PASS（所有离线测试通过，包括 TestGalaxyStaticCheck / TestWhitelist / TestSchemaValidation）

- [ ] **Step 3: 提交**

```bash
git add tools/galaxy-vibe/kernel/LibVibeKernel.galaxy
git commit -m "feat(vibe): Dispatch 注册 4 个新诊断 operation"
```

---

## Task 7: VibeHost 加 4 个便捷方法

**Files:**
- Modify: `tools/galaxy-vibe/host/vibe_host.py`（在 `query_mission` 便捷方法之后，约 718 行）
- Test: `tools/galaxy-vibe/tests/test_kernel.py`（`TestVibeHostMocked`）

- [ ] **Step 1: 写失败测试 — 加 TestVibeHostMocked 测试新便捷方法**

在 `tools/galaxy-vibe/tests/test_kernel.py` 的 `TestVibeHostMocked` 类中（约 189 行后），追加 4 个测试方法：

```python
    def test_upgrade_set_level_convenience(self):
        """upgrade_set_level 便捷方法构造正确请求。"""
        host = VibeHost()
        host.start_session()
        with patch.object(host, "_send_via_chat", return_value=True), \
             patch.object(host, "_poll_response") as mock_poll:
            mock_poll.return_value = RpcResponse(
                kind="result", session_id=host.session_id, request_id="x",
                sequence=1, operation="upgrade.set_level", error_code="OK",
                payload={"applied": 1})
            resp = host.upgrade_set_level(player=1, upgrade="ShieldWall", level=1)
        self.assertTrue(resp.is_ok)
        self.assertEqual(resp.payload["applied"], 1)

    def test_tech_tree_check_convenience(self):
        """tech_tree_check 便捷方法构造正确请求。"""
        host = VibeHost()
        host.start_session()
        with patch.object(host, "_send_via_chat", return_value=True), \
             patch.object(host, "_poll_response") as mock_poll:
            mock_poll.return_value = RpcResponse(
                kind="result", session_id=host.session_id, request_id="x",
                sequence=1, operation="tech_tree.check", error_code="OK",
                payload={"unlocked": 1, "count": 1})
            resp = host.tech_tree_check(player=1, upgrade="ShieldWall")
        self.assertTrue(resp.is_ok)
        self.assertEqual(resp.payload["unlocked"], 1)

    def test_query_unit_tags_convenience(self):
        """query_unit_tags 便捷方法构造正确请求。"""
        host = VibeHost()
        host.start_session()
        with patch.object(host, "_send_via_chat", return_value=True), \
             patch.object(host, "_poll_response") as mock_poll:
            mock_poll.return_value = RpcResponse(
                kind="result", session_id=host.session_id, request_id="x",
                sequence=1, operation="query.unit_tags", error_code="OK",
                payload={"count": 1, "tags": [12345]})
            resp = host.query_unit_tags(player=1, unit_type="Marine")
        self.assertTrue(resp.is_ok)
        self.assertEqual(resp.payload["tags"], [12345])

    def test_query_unit_attrs_convenience(self):
        """query_unit_attrs 便捷方法构造正确请求。"""
        host = VibeHost()
        host.start_session()
        with patch.object(host, "_send_via_chat", return_value=True), \
             patch.object(host, "_poll_response") as mock_poll:
            mock_poll.return_value = RpcResponse(
                kind="result", session_id=host.session_id, request_id="x",
                sequence=1, operation="query.unit_attrs", error_code="OK",
                payload={"armor": 3.0, "unit_type": "Marine"})
            resp = host.query_unit_attrs(unit_tag=12345)
        self.assertTrue(resp.is_ok)
        self.assertEqual(resp.payload["armor"], 3.0)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python tools/galaxy-vibe/tests/test_kernel.py TestVibeHostMocked`
Expected: FAIL，报 `AttributeError: 'VibeHost' object has no attribute 'upgrade_set_level'`

- [ ] **Step 3: 实现 4 个便捷方法**

在 `tools/galaxy-vibe/host/vibe_host.py` 的 `query_mission` 方法之后（约 718 行 `return self.request("query.mission", {})` 的下一行），插入：

```python
    def upgrade_set_level(self, player: int, upgrade: str, level: int) -> RpcResponse:
        """便捷方法：设置玩家升级等级。"""
        return self.request("upgrade.set_level", {
            "player": player,
            "upgrade": upgrade,
            "level": level,
        })

    def tech_tree_check(self, player: int, upgrade: str) -> RpcResponse:
        """便捷方法：检查升级是否已解锁。"""
        return self.request("tech_tree.check", {
            "player": player,
            "upgrade": upgrade,
        })

    def query_unit_tags(self, player: int = 1, unit_type: str = "") -> RpcResponse:
        """便捷方法：查询单位 tag 列表。"""
        return self.request("query.unit_tags", {
            "player": player,
            "unit_type": unit_type,
        })

    def query_unit_attrs(self, unit_tag: int) -> RpcResponse:
        """便捷方法：查询单位属性（life/armor/shields/energy）。"""
        return self.request("query.unit_attrs", {
            "unit_tag": unit_tag,
        })
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python tools/galaxy-vibe/tests/test_kernel.py TestVibeHostMocked`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add tools/galaxy-vibe/host/vibe_host.py tools/galaxy-vibe/tests/test_kernel.py
git commit -m "feat(vibe): VibeHost 新增 upgrade/tech_tree/unit_tags/unit_attrs 便捷方法"
```

---

## Task 8: 新建 vibe-diagnose.py 诊断脚本

**Files:**
- Create: `tools/galaxy-vibe/diagnose/vibe-diagnose.py`

- [ ] **Step 1: 新建诊断脚本**

创建 `tools/galaxy-vibe/diagnose/vibe-diagnose.py`：

```python
#!/usr/bin/env python3
"""Vibe 动态诊断脚本：跑期望值表，输出 PASS/FAIL 报告。

流程：reset → set_level(可选) → spawn → query_unit_tags → query_unit_attrs → assert。
全部走 VibeHost Bank RPC，不直接调 SC2API。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
VIBE_ROOT = REPO_ROOT / "tools" / "galaxy-vibe"
sys.path.insert(0, str(VIBE_ROOT))

from host.vibe_host import VibeHost, RpcResponse  # noqa: E402


def evaluate_assert(actual: dict, expected: dict) -> tuple[bool, dict]:
    """评估断言。expected 格式: {"armor": "== 3", "tech_tree_unlocked": true}。
    返回 (is_pass, details)。
    """
    details = {}
    all_pass = True
    for key, cond in expected.items():
        act_val = actual.get(key)
        if isinstance(cond, bool):
            ok = (act_val == cond) or (act_val == (1 if cond else 0))
            details[key] = {"actual": act_val, "expected": cond}
        elif isinstance(cond, str) and cond.startswith(("==", "!=", ">", "<", ">=", "<=")):
            op = cond.split()[0]
            try:
                target = float(cond.split()[1])
                act_num = float(act_val) if act_val is not None and act_val != "unavailable" else None
            except (ValueError, IndexError):
                ok = False
                act_num = None
                target = None
            if act_num is None:
                ok = False
            elif op == "==":
                ok = act_num == target
            elif op == "!=":
                ok = act_num != target
            elif op == ">":
                ok = act_num > target
            elif op == "<":
                ok = act_num < target
            elif op == ">=":
                ok = act_num >= target
            elif op == "<=":
                ok = act_num <= target
            else:
                ok = False
            details[key] = {"actual": act_val, "expected": cond}
        else:
            ok = (act_val == cond)
            details[key] = {"actual": act_val, "expected": cond}
        if not ok:
            all_pass = False
    return all_pass, details


def run_scenario(host: VibeHost, scenario: dict, map_path: str) -> dict:
    """跑一个期望值表场景，返回报告 dict。"""
    checks_result = []
    for check in scenario.get("checks", []):
        name = check["name"]
        record = {"name": name, "status": "PASS", "actual": {}, "expected": check.get("assert", {}),
                  "error_code": "OK", "notes": ""}

        # a. reset
        host.reset_scenario()

        # b. set_level（可选）
        if check.get("upgrade"):
            resp = host.upgrade_set_level(
                player=check["player"], upgrade=check["upgrade"], level=check.get("upgrade_level", 1))
            if not resp.is_ok:
                record["status"] = "ERROR"
                record["error_code"] = resp.error_code
                record["notes"] = f"upgrade.set_level 失败: {resp.error_code}"
                checks_result.append(record)
                continue

        # c. spawn
        spawn_at = check.get("spawn_at", [0, 0])
        resp = host.spawn_units(
            unit_type=check["unit_type"], count=1, player=check["player"],
            x=float(spawn_at[0]), y=float(spawn_at[1]))
        if not resp.is_ok:
            record["status"] = "ERROR"
            record["error_code"] = resp.error_code
            record["notes"] = f"unit.spawn 失败: {resp.error_code}"
            checks_result.append(record)
            continue

        # d. query_unit_tags 拿 spawned unit 的 tag
        resp = host.query_unit_tags(player=check["player"], unit_type=check["unit_type"])
        if not resp.is_ok or not resp.payload.get("tags"):
            record["status"] = "ERROR"
            record["error_code"] = resp.error_code
            record["notes"] = "query.unit_tags 无 tag 返回"
            checks_result.append(record)
            continue
        unit_tag = resp.payload["tags"][0]

        # e. query_unit_attrs
        attrs_resp = host.query_unit_attrs(unit_tag=unit_tag)
        actual = dict(attrs_resp.payload) if attrs_resp.is_ok else {}
        if not attrs_resp.is_ok:
            record["status"] = "ERROR"
            record["error_code"] = attrs_resp.error_code
            record["notes"] = f"query.unit_attrs 失败: {attrs_resp.error_code}"
            checks_result.append(record)
            continue

        # e2. tech_tree_check（可选，若 assert 含 tech_tree_unlocked）
        if "tech_tree_unlocked" in check.get("assert", {}):
            tech_resp = host.tech_tree_check(player=check["player"], upgrade=check["upgrade"])
            if tech_resp.is_ok:
                actual["tech_tree_unlocked"] = tech_resp.payload.get("unlocked", 0)
            else:
                actual["tech_tree_unlocked"] = 0

        # f. evaluate assert
        is_pass, details = evaluate_assert(actual, check.get("assert", {}))
        record["actual"] = actual
        record["status"] = "PASS" if is_pass else "FAIL"
        # 预期失败路径处理
        if check.get("expect_status") == "FAIL" and record["status"] == "FAIL":
            record["status"] = "PASS"
            record["notes"] = "预期失败路径，FAIL 已正确触发"
        checks_result.append(record)

    summary = {
        "total": len(checks_result),
        "pass": sum(1 for c in checks_result if c["status"] == "PASS"),
        "fail": sum(1 for c in checks_result if c["status"] == "FAIL"),
        "error": sum(1 for c in checks_result if c["status"] == "ERROR"),
    }
    return {
        "schemaVersion": 1,
        "scenario": scenario.get("scenario", "unknown"),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "map": map_path,
        "summary": summary,
        "checks": checks_result,
    }


def write_report(report: dict, out_dir: Path) -> tuple[Path, Path]:
    """写 report.json + report.md。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "report.json"
    md_path = out_dir / "report.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    s = report["summary"]
    lines = [
        f"# Vibe 诊断报告 — {report['scenario']}",
        "",
        f"- 地图: `{report['map']}`",
        f"- 时间: {report['timestamp']}",
        f"- 总计: {s['total']}  PASS: {s['pass']}  FAIL: {s['fail']}  ERROR: {s['error']}",
        "",
        "| check | status | actual | expected | notes |",
        "|---|---|---|---|---|",
    ]
    for c in report["checks"]:
        act = json.dumps(c["actual"], ensure_ascii=False)
        exp = json.dumps(c["expected"], ensure_ascii=False)
        lines.append(f"| {c['name']} | {c['status']} | {act} | {exp} | {c['notes']} |")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Vibe 动态诊断脚本")
    parser.add_argument("--map", required=True, help="SC2 可见的本地地图路径")
    parser.add_argument("--scenario", required=True, help="期望值表 JSON 路径")
    parser.add_argument("--port", type=int, default=8119, help="SC2 API 端口")
    parser.add_argument("--mod", default="", help="调试 mod 路径（可选）")
    parser.add_argument("--out", default="", help="报告输出目录（默认 artifacts/vibe-diagnose/<ts>）")
    args = parser.parse_args()

    scenario = json.loads(Path(args.scenario).read_text(encoding="utf-8"))
    ts = time.strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.out) if args.out else REPO_ROOT / "artifacts" / "vibe-diagnose" / ts

    host = VibeHost(sc2_port=args.port)
    if not host.start_session():
        print("[diagnose] start_session 失败", file=sys.stderr)
        return 2
    if not host.connect_sc2(map_path=args.map):
        print("[diagnose] connect_sc2 失败", file=sys.stderr)
        return 2

    print(f"[diagnose] 跑场景: {scenario.get('scenario', 'unknown')}")
    report = run_scenario(host, scenario, args.map)
    json_path, md_path = write_report(report, out_dir)
    host.close()

    s = report["summary"]
    print(f"[diagnose] 完成: total={s['total']} pass={s['pass']} fail={s['fail']} error={s['error']}")
    print(f"[diagnose] 报告: {json_path}")
    print(f"[diagnose] 报告: {md_path}")
    return 0 if s["fail"] == 0 and s["error"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 离线 smoke — --help 不报错**

Run: `python tools/galaxy-vibe/diagnose/vibe-diagnose.py --help`
Expected: 打印 argparse 帮助文本，退出码 0

- [ ] **Step 3: 提交**

```bash
git add tools/galaxy-vibe/diagnose/vibe-diagnose.py
git commit -m "feat(vibe): 新增 vibe-diagnose.py 诊断脚本（期望值表驱动）"
```

---

## Task 9: 新建 marine-baseline.json 期望值表

**Files:**
- Create: `tools/galaxy-vibe/diagnose/expectations/marine-baseline.json`

- [ ] **Step 1: 新建期望值表**

创建 `tools/galaxy-vibe/diagnose/expectations/marine-baseline.json`：

```json
{
  "scenario": "marine-baseline",
  "description": "验证 upgrade.set_level + query.unit_attrs + tech_tree.check 闭环。Marine 基础护甲 0，ShieldWall 升级后 +3。",
  "checks": [
    {
      "name": "marine_base_armor",
      "unit_type": "Marine",
      "player": 1,
      "spawn_at": [50, 50],
      "assert": { "armor": "== 0" }
    },
    {
      "name": "marine_with_shield_wall",
      "unit_type": "Marine",
      "player": 1,
      "upgrade": "ShieldWall",
      "upgrade_level": 1,
      "spawn_at": [51, 50],
      "assert": { "armor": "== 3", "tech_tree_unlocked": true }
    },
    {
      "name": "marine_nonexistent_upgrade",
      "unit_type": "Marine",
      "player": 1,
      "upgrade": "NonExistent",
      "upgrade_level": 1,
      "spawn_at": [52, 50],
      "expect_status": "FAIL",
      "assert": { "tech_tree_unlocked": false }
    }
  ]
}
```

> 注：ShieldWall 给 Marine +3 护甲是 SC2 标准 Catalog 行为。真机若实测值非 3（版本差异），以实测值调整此表，不视为代码缺陷。

- [ ] **Step 2: 提交**

```bash
git add tools/galaxy-vibe/diagnose/expectations/marine-baseline.json
git commit -m "feat(vibe): 新增 marine-baseline 期望值表"
```

---

## Task 10: 集成 Kernel 到 vibe 测试地图

**Files:**
- 无代码文件改动；产物为地图 MPQ 内的 LibVibeKernel.galaxy 替换

> **前置说明：** Galaxy 无法离线执行，必须把新 `kernel/LibVibeKernel.galaxy` 集成进 `亡者之夜_vibe_live.SC2Map` 的 `Base.SC2Data`。若现有集成工具/流程不可用，记录为 blocker（符合 AGENTS.md evidence 规则），不跳过真机验证。

- [ ] **Step 1: 确认 vibe 测试地图路径与现有集成方式**

Run: `dir /b "tools\galaxy-vibe\*.SC2Map" "tools\galaxy-vibe\maps" 2>nul` 或用 Glob 查找 `**/亡者之夜_vibe_live.SC2Map`
- 若找到地图 + 集成脚本：用该脚本把新 Kernel 注入地图
- 若无集成脚本：尝试用 MPQ 编辑器（如 `tools/mpq/` 下工具）替换地图内 `Base.SC2Data/LibVibeKernel.galaxy`
- 若都不可用：记录 blocker，跳过 Task 11，在报告里标注"真机验证因 Kernel 集成工具缺失未执行"

- [ ] **Step 2: 验证地图内 Kernel 已更新（静态证据）**

用 MPQ 工具读出地图内 `LibVibeKernel.galaxy`，Grep 查 `HandleUpgradeSetLevel`：
Expected: 命中，证明新 Kernel 已集成

- [ ] **Step 3: 提交集成产物（若地图在仓库内）**

```bash
git add <地图路径>
git commit -m "chore(vibe): vibe 测试地图集成 Stage 1 Kernel（4 个新 handler）"
```

> 若地图不在仓库内（gitignored），跳过提交，仅在 log 记录集成完成。

---

## Task 11: 真机验证 marine-baseline

**Files:**
- 生成: `artifacts/vibe-diagnose/<timestamp>/report.json`
- 生成: `artifacts/vibe-diagnose/<timestamp>/report.md`

> **启动规则（AGENTS.md）：** 必须用 `launch-galaxy-vibe.ps1` 启动，依赖 Wait-GameReady 信号，禁止固定时间盲等。launcher 退出码 0 视为加载完成。退出后复核 GameLogs 无新增 ScriptError。

- [ ] **Step 1: 启动 SC2 + vibe 测试地图**

Run（PowerShell）:
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\tools\galaxy-vibe\launch-galaxy-vibe.ps1" -Port 8119 -Map "<vibe测试地图绝对路径>" -Repl
```
Expected: launcher 退出码 0，打印加载完成信号

- [ ] **Step 2: 复核 GameLogs 无新增 ScriptError**

Run:
```powershell
Get-ChildItem "$env:USERPROFILE\Documents\StarCraft II\GameLogs\ScriptError*.txt" | Where-Object { $_.LastWriteTime -gt (Get-Date).AddMinutes(-5) }
```
Expected: 无输出（无新增 ScriptError）。若有新增，记录错误内容，修复后重跑。

- [ ] **Step 3: 跑诊断脚本**

Run:
```powershell
python tools\galaxy-vibe\diagnose\vibe-diagnose.py --map "<vibe测试地图路径>" --scenario tools\galaxy-vibe\diagnose\expectations\marine-baseline.json --port 8119
```
Expected:
- `marine_base_armor` = PASS（armor == 0）
- `marine_with_shield_wall` = PASS（armor == 3, tech_tree_unlocked == 1）
- `marine_nonexistent_upgrade` = PASS（预期失败路径，tech_tree_unlocked == 0）
- 退出码 0

- [ ] **Step 4: 若 armor 实测值与期望不符，调整期望值表**

若 `marine_with_shield_wall` FAIL 且 actual.armor != 3：
- 用实测 armor 值更新 `marine-baseline.json` 的 `assert.armor`
- 重跑 Step 3 确认 PASS
- 在报告 notes 记录"实测值 X，已调整期望值表"

- [ ] **Step 5: 提交诊断报告**

```bash
git add artifacts/vibe-diagnose/
git commit -m "test(vibe): Stage 1 真机验证 marine-baseline 诊断闭环 PASS"
```

- [ ] **Step 6: 推送全部 Stage 1 改动**

```bash
git pull --ff-only
git push
```

---

## 验收清单

- [ ] whitelist.json 含 4 个新 operation
- [ ] LibVibeKernel.galaxy 含 4 个新 handler + Dispatch 注册
- [ ] vibe_host.py 含 4 个便捷方法
- [ ] test_kernel.py 离线测试全 PASS
- [ ] vibe-diagnose.py + marine-baseline.json 存在
- [ ] 真机跑 marine-baseline：3 个 check 全 PASS
- [ ] 无新增 ScriptError
- [ ] report.json + report.md 生成到 artifacts/vibe-diagnose/
- [ ] 全部改动已 commit + push

## Stage 2/3 演进（不在本计划）

- **Stage 2**：`query.trainable_units` + `query.production_queue` + 载体切 Reborn 真实 mod
- **Stage 3**：根因定位（ScriptError 关联 + Catalog 缺陷定位）+ 自动 patch
