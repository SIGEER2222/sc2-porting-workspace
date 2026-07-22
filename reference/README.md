# reference 目录总览

本目录收录与 StarCraft II 模组开发、移植相关的开源参考仓库，作为 AI 开发 SC2 mod 工作流的外部输入源。所有子目录均以 `git submodule` 方式注册（见 [../.gitmodules](../.gitmodules)），仅作为只读参考，不修改其内容（详见 [../AGENTS.md](../AGENTS.md) "External tool source remains in its own Git repository" 约束）。

使用前请留意各仓库 README 中的维护状态声明（部分仓库已归档或停止更新）。

---

## 按类型分组

### 1. 官方/原生游戏数据

| 仓库 | 类型 | 功能 | 参考价值 |
|---|---|---|---|
| [SC2GameData](sc2mapster/SC2GameData) | 游戏数据 | 收集 SC2 原生 GameData / UI / Galaxy 脚本等数据文件 | **高** — 直接包含官方 `alliedcommanders.sc2mod`（合作指挥官）与全部突变器模组源文件，是合作模式机制研究最权威的原型参考 |

### 2. SC1→SC2 地图移植范例

| 仓库 | 类型 | 功能 | 参考价值 |
|---|---|---|---|
| [SC2BW](SC2BW) | 地图移植 | SC1 Brood War → SC2 单位/机制总 Mod | **高** — SC1→SC2 单位移植最直接范例，含完整 `.SC2Mod` 数据/Actor 结构 |
| [SC2plusSCBW](SC2plusSCBW) | 地图移植 | "Starcraft: Evolution Complete" — 以最小化方式平行引入 BW 单位不与原版冲突 | **高** — 示范如何在 SC2 中引入 SC1 单位而不覆盖原版数据，对 mod 兼容性处理关键 |
| [Cerebrates](Cerebrates) | 地图移植 | SC1 Cerebrates 英雄竞技场 SC2 重制 | 中-高 — SC1 地图→SC2 完整复刻样本，触发器/英雄技能迁移参考 |

### 3. 大型 SC2 触发器 RPG 工程

| 仓库 | 类型 | 功能 | 参考价值 |
|---|---|---|---|
| [Night-of-the-Dead](Night-of-the-Dead) | 触发器 RPG | SC2 经典生存地图，777 commits，含完整 Mod 依赖与测试流程 | 中 — 大型 Mod+Map 工程范例，触发器组织/SC2Bank 存档/测试调试流程参考 |

### 4. Galaxy 脚本与数据工具链

| 仓库 | 类型 | 功能 | 参考价值 |
|---|---|---|---|
| [sc2-galaxy-toolkit](sc2-galaxy-toolkit) | LSP 工具 | VS Code 扩展，为 SC2 Galaxy 脚本提供语言支持（plaxtony 后继，活跃维护） | 中 — Galaxy 脚本 LSP 实现，monorepo（pnpm + TypeScript + vitest），对自建辅助工具链有参考 |
| [plaxtony](plaxtony) | 解析库（已归档） | Galaxy 脚本解析/静态分析/LSP、Triggers XML 解析、GameData catalogs 解析 | 中 — 已归档快照，提供 Galaxy 解析/类型检查实现思路；新版见 sc2-galaxy-toolkit |
| [sc2layout-schema](sc2mapster/sc2layout-schema) | 布局模式 | SC2Layout 文档 XML Schema 定义，用于校验与编辑器扩展（已弃用，迁至 sc2-galaxy-toolkit） | 中 — 若涉及自定义 UI（SC2Layout）可作语法校验参考 |
| [sc2mapster-docs-generator](sc2mapster/sc2mapster-docs-generator) | 文档生成器 | 为 Galaxy 脚本与 SC2Layout 生成 API 文档站点的静态生成器 | 中 — 若需自建 Galaxy API 参考文档站可复用 |

### 5. SC2 编辑器数据工具

| 仓库 | 类型 | 功能 | 参考价值 |
|---|---|---|---|
| [Starcraft-2-Data-Wizards](Starcraft-2-Data-Wizards) | 数据工具 | SC2 编辑器"数据向导"（BlizWiz）样例与文档，可批量自动生成武器/导弹/通用任务数据 | 中 — `.BlizWiz` 是编辑器原生扩展点，对批量复刻 SC1 单位/武器数据可提效 |
| [sc2mapster-tools](sc2mapster/sc2mapster-tools) | 工具集 | "处理 Blizzard 数据的零散脚本与工具" | 低 — 仅一个 `update.lua`，内容稀少 |

### 6. Neuro 外部集成（mod 内外部通信）

| 仓库 | 类型 | 功能 | 参考价值 |
|---|---|---|---|
| [SC2-Neuro-API-Integration](SC2-Neuro-API-Integration) | Neuro 集成 | 将 Neuro API 接入 SC2，Python websocket ↔ Galaxy 触发器通信 | 中 — `.SC2Mod`/`.SC2Map` 实物 + Banks 持久化 + 外部服务通信完整链路文档，对"外部数据驱动 mod 内行为"有直接参考 |
| [SC2-Neuro-WoL-Integration](SC2-Neuro-WoL-Integration) | Neuro 集成 | 基于 API Integration 打造的 WoL 战役 Neuro 体验，含能力持久化/间歇期交互 | 中 — 战役类 mod 的能力体系设计与玩家提示规范借鉴 |

### 7. SC2 AI 框架（与 mod 移植关系较远）

| 仓库 | 类型 | 功能 | 参考价值 |
|---|---|---|---|
| [python-sc2](python-sc2) | AI 框架 | Python SC2 API 客户端，封装 raw scripted interface | 低 — 面向 AI Bot 开发，与 Galaxy 触发器 mod 移植技术栈不重合 |
| [ares-sc2](ares-sc2) | AI 框架 | python-sc2 之上的扩展层（行为系统/Mediator/影响图） | 低 — 行为树/Mediator 架构思路对触发器组织有少量启发 |
| [awesome-sc2-ai](awesome-sc2-ai) | 资源清单 | SC2 AI 相关代码与资源汇总（APIs/框架/Bots/ML/教程） | 低 — 纯索引型，可作 SC2 生态查阅入口 |

### 8. 教程与社区文档

| 仓库 | 类型 | 功能 | 参考价值 |
|---|---|---|---|
| [blizzard-tutorials](sc2mapster/blizzard-tutorials) | 教程 | 原 Blizzard 官方 SC2 Editor 教程，SC2Mapster 社区接手维护（readthedocs） | 中 — 编辑器使用/触发器/数据编辑基础知识入口 |
| [mkdocs-sc2](sc2mapster/mkdocs-sc2) | 文档源 | SC2 开发环境搭建 mkdocs 文档（纯文本数据格式工作流） | 中 — SC2 工程化开发流程借鉴 |
| [sc2mapster-github-io](sc2mapster/sc2mapster-github-io) | 站点源 | SC2Mapster 社区 GitHub Pages 源码，含深度指南与开源地图索引 | 中 — 教程参考 + 开源地图清单是寻找类似合作/防守 mod 案例的入口 |

### 9. 社区站点爬虫

| 仓库 | 类型 | 功能 | 参考价值 |
|---|---|---|---|
| [sc2mapster-crawler](sc2mapster/sc2mapster-crawler) | 爬虫 | Puppeteer + Cheerio 爬取 sc2mapster.com 项目/文件/图片/帖子 | 低 — 仅用于批量抓取社区站资源，与游戏数据无直接关系 |

---

## 按参考价值快速索引

### 高（直接对应移植工作）

- **[SC2GameData](sc2mapster/SC2GameData)** — 官方 `alliedcommanders.sc2mod` + 全部突变器源文件
- **[SC2BW](SC2BW)** — SC1→SC2 单位移植完整 `.SC2Mod` 范式
- **[SC2plusSCBW](SC2plusSCBW)** — SC1 单位与 SC2 原版数据共存方案

### 中-高

- **[Cerebrates](Cerebrates)** — SC1 地图→SC2 完整复刻样本

### 中

- **[Night-of-the-Dead](Night-of-the-Dead)** — 大型 Mod+Map 工程组织范例
- **[SC2-Neuro-API-Integration](SC2-Neuro-API-Integration)** — mod 内外部通信链路（Banks/websocket）
- **[SC2-Neuro-WoL-Integration](SC2-Neuro-WoL-Integration)** — 战役类 mod 能力体系设计
- **[sc2-galaxy-toolkit](sc2-galaxy-toolkit)** — Galaxy 脚本 LSP（活跃维护）
- **[plaxtony](plaxtony)** — Galaxy 解析库（归档快照，新版见上）
- **[Starcraft-2-Data-Wizards](Starcraft-2-Data-Wizards)** — BlizWiz 批量数据生成向导
- **[sc2layout-schema](sc2mapster/sc2layout-schema)** / **[sc2mapster-docs-generator](sc2mapster/sc2mapster-docs-generator)** — UI 校验与文档生成
- **[blizzard-tutorials](sc2mapster/blizzard-tutorials)** / **[mkdocs-sc2](sc2mapster/mkdocs-sc2)** / **[sc2mapster-github-io](sc2mapster/sc2mapster-github-io)** — 编辑器与工程化教程

### 低

- **[python-sc2](python-sc2)** / **[ares-sc2](ares-sc2)** / **[awesome-sc2-ai](awesome-sc2-ai)** — AI Bot 技术栈
- **[sc2mapster-tools](sc2mapster/sc2mapster-tools)** / **[sc2mapster-crawler](sc2mapster/sc2mapster-crawler)** — 内容稀少或与游戏数据无关

---

## 维护说明

- 新增参考仓库：`git submodule add <url> reference/<名称>`，并在本 README 对应分组中追加条目
- 所有 submodule 均为只读引用，禁止直接修改其内容（见 [../AGENTS.md](../AGENTS.md)）
- 仓库列表与 URL 完整定义见 [../.gitmodules](../.gitmodules)
