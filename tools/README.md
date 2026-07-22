# Tools 目录规范

本文件约束后续 AI 与贡献者在 `tools/` 下放置脚本、推算路径、适配 mod 时的行为。

## 目录结构

```
tools/
├── launchers/        # 启动 SC2 游戏测试的 PowerShell 脚本
├── runtime-bridge/   # 与运行中 SC2 实例交互（bank 读写、输入注入、OCR）
├── analysis/         # 静态分析（catalog XML、galaxy AST、边界提取、链对比）
├── mpq/              # MPQ 打包/解包工具（MPQEditor.exe + 自研脚本，见 mpq/README.md）
├── utils/            # 工作区管理（workspace.mjs）与通用小工具
├── kb/               # 知识库向量索引（独立模块，见 kb/README.md）
├── tooling/          # 工具边界文档
└── .codex/           # Codex skills（AI 行为约束）
```

## 脚本放置规则（硬约束）

1. **新脚本按功能域放入对应子目录，禁止放 `tools/` 根目录。**
2. 功能域划分：
   - `launchers/`：启动游戏、选择 composition、运行测试基线
   - `runtime-bridge/`：通过 bank / 输入 / OCR 与运行中游戏交互
   - `analysis/`：对 mod / map 做静态分析（catalog XML、galaxy AST）
   - `mpq/`：MPQ 打包/解包工具（含 `MPQEditor.exe` 二进制 + 自研 Python/PS1 脚本，自包含路径推算，不依赖 `$WorkspaceRoot`）
   - `utils/`：工作区管理（`workspace.mjs`）和通用小工具（如 `add-bom.ps1`）
3. 跨域脚本不得互相直接引用；如需复用，提取到 `utils/` 或通过 workspace 命令组合。
4. `mpq/` 是自包含工具集，脚本用 `$scriptDir`/`$skillDir` 推算同目录 exe 与 py，不遵循上文的 `$WorkspaceRoot` 推算约定。

## 路径引用约定（硬约束）

脚本位于 `tools/<子目录>/` 下，推算 `sc2-porting-workspace/` 根时需多上溯一层。

### PowerShell 脚本

```powershell
# 正确：从 tools/launchers/xxx.ps1 推算 sc2-porting-workspace/
$WorkspaceRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Sc2WorkspaceRoot = Split-Path -Parent $WorkspaceRoot  # -> SC2VibeTools/
```

- 同目录脚本互引（如 `run-test-alenger3.ps1` 调 `launch-cmre-alenger.ps1`）用 `$PSScriptRoot` 直接拼接，无需多层级。
- 禁止用硬编码绝对路径推算工作区根。

### Node.js (mjs) 脚本

```javascript
const scriptDir = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(scriptDir, "..", ".."); // -> sc2-porting-workspace/
```

- 所有 `analysis/` 与 `utils/` 下的 mjs 脚本统一用 `resolve(scriptDir, "..", "..")` 推算 repoRoot。

## 历史记录不修改原则

`src/stages/` 与 `src/projects/` 下的 `result.json` / `log.md` / `plan.md` / `issues.json` 中引用的旧脚本路径（如 `tools/workspace.mjs`、`scripts/analyze-galaxy.mjs`）是**审计轨迹，禁止修改**。这些记录反映当时执行命令的真实状态，路径不一致是历史迁移的正常产物。只有活跃文档（`README.md`、`docs/workflow.md`、`tools/tooling/README.md`）才同步更新为新路径。

## SC2 API Mod 适配方向（方案 A：动态枚举注入）

`reference/python-sc2` 与 `reference/ares-sc2` 是外部参考库（已 Git 忽略，仅本地查阅），**不得修改其源码**。mod 适配代码须写在本工作区内。

### 核心障碍

python-sc2 与 ares-sc2 默认对 mod 自定义单位 / 技能失效：

1. `python-sc2/sc2/game_data.py:27-30` 用 `AbilityId` 枚举过滤 ability，mod 自定义 ability 被丢弃，导致建造 / 生产 / 施法指令无法下发。
2. `python-sc2/sc2/ids/unit_typeid.py` 是硬编码 `enum.Enum`，mod 自定义单位只能用数值 id 访问。
3. `ares-sc2/src/ares/dicts/` 下所有 dict（`UNIT_DATA`、`UNIT_TRAINED_FROM`、`cost_dict` 等）全是 `UnitTypeId.XXX` 硬编码，ares 的 Build Runner / Production Controller / Combat Maneuver 在 mod 单位上完全失效。

### 方案 A 实施约束（硬约束）

后续 AI 实施 mod 适配时**必须遵循方案 A**，不得改用纯数值 id 路径（方案 B）或从 catalog 重建 dict（方案 C）：

1. **动态枚举注入**：在 `BotAI.on_start` 阶段，从 `game_data.units` / `game_data.abilities` 读取 mod 自定义单位 / 技能，动态注册到 `UnitTypeId` / `AbilityId` 枚举（Python `enum.Enum` 支持运行时扩展）。
2. **放宽 GameData 过滤**：覆写或修补 `GameData.abilities` 构造逻辑，不再用 `AbilityId` 枚举集过滤，改为接受所有 `available` 的 ability。
3. **动态补充 ares dict**：对 `ares-sc2` 的硬编码 dict，按 mod catalog 动态生成补充条目（单位成本、训练来源、科技别名等），注入到 ares 的 Build Runner / Production Controller。
4. **适配层位置**：mod 适配代码写在本工作区 `src/` 下对应的 adapter 模块中，不污染 `reference/`。

### 参考路径

- python-sc2 GameData 过滤逻辑：`reference/python-sc2/sc2/game_data.py`
- python-sc2 单位类型枚举：`reference/python-sc2/sc2/ids/unit_typeid.py`
- ares-sc2 硬编码 dict 目录：`reference/ares-sc2/src/ares/dicts/`
- ares-sc2 Build Runner：`reference/ares-sc2/src/ares/build_runner/`
- ares-sc2 宏行为（建造 / 生产 / 升级）：`reference/ares-sc2/src/ares/behaviors/macro/`
