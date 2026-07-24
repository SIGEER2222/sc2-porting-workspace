# Replay-based Runtime Evidence

> **状态**：已验证可用（能读取 mod 自定义单位数据）
> **验证时间**：2026-07-24
> **原理**：SC2 游戏运行时自动记录所有单位事件到录像文件，用 mpyq + s2protocol 离线解析 `replay.tracker.events` 流
> **配套方法**：[SC2 API In-Game 路径](#sc2-api-in-game-路径已验证)（已打通，能验证建造面板可见性，弥补 replay 局限）

## 原理

SC2 游戏每局结束（正常退出）后会自动保存 `LastReplay.SC2Replay`。录像文件是 MPQ 归档，内部包含：
- `replay.details`：玩家、地图、时间等元信息
- `replay.tracker.events`：完整的单位事件流（创建/死亡/建筑完成）
- `replay.game.events`：玩家操作事件

`replay.tracker.events` 中的关键事件类型：
- `NNet.Replay.Tracker.SUnitBornEvent`：单位被生成（触发器创建、训练完成）
- `NNet.Replay.Tracker.SUnitInitEvent`：建筑开始建造
- `NNet.Replay.Tracker.SUnitDoneEvent`：建筑建造完成（标记为"结构"）
- `NNet.Replay.Tracker.SUnitDiedEvent`：单位/建筑死亡/被摧毁

每个事件携带：`m_unitTypeName`（单位类型名）、`m_controlPlayerId`（所属玩家）、`m_x`/`m_y`（位置）、`_gameloop`（游戏帧）。

## 工作流

1. 用 `launch-cmre-alenger.ps1` 普通模式启动带 mod 的游戏（不带 `-ListenPort`）
2. 等待游戏加载完成（launcher 的 `Wait-GameReady` 信号检测，退出码 0 即完成）
3. 游戏运行 N 秒（让单位/建筑生成）
4. **正常退出游戏**（必须正常退出，`Stop-Process -Force` 不会保存录像）
5. SC2 自动保存 `LastReplay.SC2Replay`
6. 用 `replay-probe.py` 解析录像 → 输出 `events.ndjson` + `verdict.json`

## 实测证据

解析 `丧尸围城-合作指挥官mod适配(勿选诺娃霍纳).SC2Replay`（base_build 96999）：

- tracker events: **5028 个**
- born/init events: **2571 个**
- died events: **2066 个**
- done events（建筑完成）: **38 个**

成功读取 mod 自定义单位（Player 1）：
| 单位类型 ID | 中文名 | 数量 |
|------------|--------|------|
| `3diguolaogong` | 帝国劳工 | 32 |
| `3chongfengduixunhangjian` | 冲锋队巡航舰 | 21 |
| `3zidonghuajinglianchang` | 自动化精炼厂 | 12 |
| `3diguoqianshaojidi` | 帝国前哨基地 | 9 |
| `3huangjiafangkongta` | 皇家防空塔 | 4 |
| `3huguozhanjiang` | 护国战将 | 4 |
| `3gongtingmoshushi` | 宫廷魔导师 | 3 |
| `3diguobingying` | 帝国兵营 | 2 |
| `3diguogongchang` | 帝国工厂 | 2 |
| `3diguogongchengzhan` | 帝国工程站 | 1 |

## 依赖

- `mpyq`（MPQ 归档读取）
- `s2protocol` v5.0.16.97563（协议解码，向后兼容 base_build 96999）

## 能力边界（关键局限）

### ✅ 能证明

- **单位存在性**：replay 里出现的单位，游戏运行时确实存在过（replay 记录的是真实发生的事件）
- **单位类型**：能读取 mod 自定义单位的类型 ID（如 `3diguolaogong`）
- **所属玩家**：每个单位属于哪个玩家
- **位置**：单位在地图上的坐标
- **时间线**：单位在哪个 game loop 被创建/死亡
- **建筑完成状态**：通过 `SUnitDoneEvent` 判断建筑是否建造完成

### ❌ 不能证明

- **建造面板可见性**：replay 不记录玩家的建造面板有哪些按钮。某建筑在 replay 里出现（被建造过），不能证明它的建造按钮在面板里可见——可能是触发器用 `UnitCreate` 直接生成的，而非玩家通过建造技能建造。
- **训练技能可用性**：同上，单位被训练出来不代表训练按钮对玩家可见。
- **Tech Tree 解锁状态**：replay 不记录引擎层的 Requirement/State 判定。某单位被建造可能是因为触发了特定条件，不能证明它在通用场景下可建造。
- **完整性（缺失检测）**：replay 里没有某单位的事件，**不能证明**该单位在游戏内无法建造——可能是玩家没去建造它，或者游戏时长不够。这是最大的局限：**replay 只能证明"存在"，不能证明"不存在"**。

### ⚠️ 与游戏内表现一致性风险

用户提出的核心疑虑：**解析出来了，但玩家游戏内看到的并没有对应的建造技能/训练技能，或者部分单位建筑缺失**。

这正是 replay 方法的根本局限：

| 场景 | replay 表现 | 游戏内真实情况 | 一致性 |
|------|-----------|--------------|--------|
| 触发器 `UnitCreate` 生成的单位 | ✅ 有事件 | ❓ 玩家可能无法主动建造 | 不一致 |
| 玩家通过建造技能建造的建筑 | ✅ 有事件 | ✅ 建造按钮可见 | 一致 |
| 玩家通过训练技能训练的单位 | ✅ 有事件 | ✅ 训练按钮可见 | 一致 |
| 玩家没建造的单位（但本可建造） | ❌ 无事件 | ✅ 建造按钮可见 | 不一致（假阴性） |
| 被 TechTree 锁定无法建造的单位 | ❌ 无事件 | ❌ 建造按钮不可见 | 一致（但无法区分） |

**结论**：replay 解析无法区分"单位是被触发器生成的"还是"被玩家主动建造的"，也无法检测"可建造但未建造"的单位。要验证建造面板/训练技能的可用性，必须用 SC2 API 的 `RequestQueryAvailableAbilities`（查询单位真实可用能力，含引擎 TechTree 判定）。

## 替代方案对比

| 方案 | 能力 | 状态 |
|------|------|------|
| **Replay 解析（本方法）** | 读取单位存在性、类型、玩家、位置 | ✅ 可用，但只能证明"存在" |
| **SC2 API `RequestQueryAvailableAbilities`** | 查询建造面板真实可用能力（含引擎 TechTree 判定） | ✅ 已打通（见下方章节） |
| SC2 API `RequestQueryBuildingPlacement` | 测试建造放置合法性 | ⚠️ 同 in_game 路径，未单独验证 |
| RuntimeProbe Bank（已禁用） | Galaxy 代码自写 Bank 诊断 | ❌ 已禁用（AI 自写自审） |

## SC2 API In-Game 路径（已验证）

> **状态**：✅ 已打通（2026-07-24）
> **核心突破**：用打包后的 MPQ 地图（含 launcher 补丁）通过 `RequestCreateGame` + `RequestJoinGame` 进入 `in_game` 状态，能用 `RequestQueryAvailableAbilities` 实时查询 mod 单位的可用能力，**直接弥补 replay 无法验证建造面板可见性的局限**。

### 工作流

1. 用 `launch-cmre-alenger.ps1 -ListenPort 5000 -LegacyRootOverride "E:\Code\MyMod\SC2\合作指挥官-起义狂潮"` 启动 SC2（API 模式，不加载地图，停在 `launched` 状态）
2. 用 `tools/runtime-bridge/mpq_pack.py` 把 liveMap 目录（含 launcher 注入的 galaxy 补丁和 mod 依赖）打包成 MPQ 文件：
   ```powershell
   python tools/runtime-bridge/mpq_pack.py "E:\SC2\SC2new\StarCraft II\Maps\亡者之夜.SC2Map" "E:\SC2\SC2new\StarCraft II\Maps\DeadOfNight_live_packed.SC2Map"
   ```
3. Python 脚本通过 WebSocket 连接 `ws://127.0.0.1:5000/sc2api`，发送：
   - `RequestPing` 确认 SC2 进入 `launched` 状态
   - `RequestCreateGame{local_map: {map_path: <packed.SC2Map>}, realtime: true}` → 状态变 `init_game`
   - `RequestJoinGame{race: Terran, options: {raw: true, show_placeholders: true}}` → 状态变 `in_game`
   - `RequestData{ability_id: true, unit_type_id: true}` → 获取 ability_id ↔ link_name 映射、unit_type_id ↔ name 映射
   - **等待 30+ 秒**让游戏初始化（关键！10 秒不够，会返回 0 abilities）
   - `RequestObservation` → 获取场上单位列表（含 tag/owner/pos）
   - `RequestQuery{abilities: [RequestQueryAvailableAbilities{unit_tag: <tag>}]}` → 查询该单位当前可用能力
4. 解析返回的 `AvailableAbility` 消息列表，用 `a.ability_id` 索引 ability_map 得到 link_name（如 `3jianzao1`）

### 实测证据（2026-07-24）

测试条件：亡者之夜 + TerranAlenger3，打包 MPQ 22MB（73 个文件），realtime 模式。

**劳工（3diguolaogong, unit_type_id=4382）能力查询：**

| game_loop | 等待时间 | abilities 总数 | mod 能力（3 开头） |
|-----------|---------|---------------|-------------------|
| 2902 | 30s | 11 | `3jianzao2`, `3zhandouzhengzhao` |
| 3343 | 50s（再等 20s） | 12 | `3jianzao1`, `3jianzao2`, `3zhandouzhengzhao` |

**关键发现**：`3jianzao1` 在 game_loop=2902 时不可见，在 game_loop=3343 时变为可见，说明 `RequestQueryAvailableAbilities` **真实反映引擎 TechTree 的动态解锁状态**（前置建筑/科技完成后才解锁）。这正是 replay 方法无法做到的。

**前哨基地（3diguoqianshaojidi, unit_type_id=4390）能力查询：**
- 5 个 abilities，3 个 mod：`3diguoqianshaojidiTransport`, `3shengkong1`, `3xunlian1`
- 标准能力：`RallyCommand`

### 与游戏内表现一致性

**✅ 直接解决 replay 的核心局限**：`RequestQueryAvailableAbilities` 返回的能力列表，就是玩家在游戏内选中该单位时建造面板上**实际可见且可用**的按钮（引擎层 TechTree 判定，含 Requirement/Suppressed 状态检查）。

| 场景 | replay 表现 | SC2 API 表现 | 一致性 |
|------|-----------|------------|--------|
| 触发器 `UnitCreate` 生成的单位 | ✅ 有事件 | ❓ 不影响（查的是建造方单位） | API 更准 |
| 玩家通过建造技能建造的建筑 | ✅ 有事件 | ✅ 建造能力可见 | 一致 |
| 玩家通过训练技能训练的单位 | ✅ 有事件 | ✅ 训练能力可见 | 一致 |
| 玩家没建造的单位（但本可建造） | ❌ 无事件（假阴性） | ✅ 建造能力可见 | API 更准 |
| 被 TechTree 锁定无法建造的单位 | ❌ 无事件 | ❌ 建造能力不可见 | 一致 |
| 能力随游戏推进动态解锁 | ❌ 无法反映 | ✅ 实时反映 | API 更准 |

### 关键实现细节

**1. MPQ 打包（`tools/runtime-bridge/mpq_pack.py`）**

SC2 API 的 `RequestCreateGame.local_map.map_path` 只接受 `.SC2Map` 文件（MPQ 归档），不接受目录路径。launcher 生成的是 liveMap 目录（含补丁），必须打包成 MPQ：
- 用纯 Python 实现 MPQ v0 写入（无压缩、单 unit 文件）
- hash/block 表必须用 `mpq_encrypt` 加密（key 由 `'(hash table)'` / `'(block table)'` 派生）
- 添加 `(listfile)` 虚拟文件供 mpyq 读取

**2. 必须用 `-LegacyRootOverride`**

launcher 默认 `LegacyRoot = <SC2VibeTools>/合作指挥官-起义狂潮`，但实际路径是 `E:\Code\MyMod\SC2\合作指挥官-起义狂潮`。不加 `-LegacyRootOverride` 会报 `common.ps1 not found`。

**3. 必须等待 30+ 秒**

realtime 模式下，游戏初始化需要时间（触发器执行、TechTree 设置）。10 秒不够，`RequestQueryAvailableAbilities` 会返回 0 abilities（曾误判为 API 限制）。30 秒后能查到 11+ abilities。

**4. `AvailableAbility` 消息处理**

`resp.query.abilities[0].abilities` 是 `repeated AvailableAbility`，每个元素是消息（含 `ability_id` / `requires_point` / `player_id`），不是 uint32。必须用 `a.ability_id` 索引 `ability_map`，不能直接用 `a`（会触发 `unhashable object` 错误）。

### 依赖

- `aiohttp`（WebSocket 客户端）
- `s2clientprotocol`（protobuf 协议，需设置 `PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python`）
- `reference/SC2-Neuro-API-Integration`（提供 `s2clientprotocol` 包）

### 相关脚本

**正式工具（`tools/runtime-bridge/`，git 跟踪）：**
- `sc2api_worker_probe.py`：劳工建造能力 + placement 探测（2026-07-24 修复 `AvailableAbility` 索引 bug）
- `mpq_pack.py`：MPQ 打包工具（liveMap 目录 → `.SC2Map` 文件）
- `replay-probe.py`：replay 解析工具（mpyq + s2protocol）

**临时验证脚本（`artifacts/runtime/`，gitignore 不跟踪）：**
- `_diag_abilities_zero.py`：能力查询诊断脚本（首次验证 SC2 API 能查到 mod 能力）
- `_test_livemap_packed.py`：完整 SC2 API 流程测试（create + join + query）

**launcher（`tools/launchers/`）：**
- `launch-cmre-alenger.ps1`：`-ListenPort <port>` 启用 API 模式（不加载地图，由 Python 脚本通过 `RequestCreateGame` 加载）

## 修复记录

`replay-probe.py` 原脚本用 `build(base_build)` 查找 protocol 模块，但 s2protocol 库没有 base_build 96999 对应的模块（最新是 97563）。需要用 `latest()` 替代 `build(base_build)` 实现向后兼容解码。

## 相关文档

- [deprecated-runtime-probe.md](./deprecated-runtime-probe.md)：禁用 RuntimeProbe 作为 runtime 证据
- [workflow.md](./workflow.md)：runtime 验证工作流
- [superpowers/specs/2026-07-23-runtime-evidence-enforcement-design.md](./superpowers/specs/2026-07-23-runtime-evidence-enforcement-design.md)：runtime 证据强制设计
