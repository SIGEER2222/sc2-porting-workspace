# SC2 Galaxy / SC2Data Agent Skills

本目录收录 **20 个** StarCraft II 编辑器 / Galaxy Script 的 Agent Skill（供 Claude Code、WorkBuddy 等 AI 编码助手使用），作为 **项目本地 skill 源码** 纳入 git 版本控制——克隆本仓库即可获得，无需从外部重新安装。

## 来源
- 上游仓库：[KimPlaybit/starcraft-2-editor-skills](https://github.com/KimPlaybit/starcraft-2-editor-skills)
- 在 SkillsMP / LobeHub 同名发布（作者 KimPlaybit）
- 镜像入库日期：2026-07-23

## 包含的 skill（20 个）

### Galaxy Script 系列（13）
| Skill | 内容 |
|---|---|
| galaxy-language-fundamentals | 语言语法与基础类型 |
| galaxy-triggers-and-functions | 触发器 / 函数 / 异步执行 |
| galaxy-math-strings-conversion | 数学 / 字符串 / 类型转换 |
| galaxy-units-and-groups | 单位与单位组 |
| galaxy-players-and-alliances | 玩家 / 联盟 / 胜利条件 |
| galaxy-ai-and-techtree | AI / 科技树 / 波次 |
| galaxy-ui-and-dialogs | 对话框 / UI / XML 框架 |
| galaxy-sound-camera-environment | 音效 / 相机 / 环境 |
| galaxy-points-regions-geometry | 点 / 区域 / 几何 / 寻路 |
| galaxy-actor-and-visuals | actor 与视觉效果 |
| galaxy-code-organization | 文件结构 / 模块化 |
| galaxy-debug-data-catalog | 调试输出 / Data Table / Catalog |
| galaxy-game-systems | Bank 存读 / 生成器 / 波次 / 营地 |

### SC2Data 编辑器系列（7）
| Skill | 内容 |
|---|---|
| sc2data-units-abilities | 单位 / 技能 / 移动器 |
| sc2data-behaviors-validators | 行为 / 验证器 |
| sc2data-effects-weapons | 效果 / 武器 / 升级 |
| sc2data-actors-visuals | actor / 视觉效果 |
| sc2data-wizards | 自动化向导 |
| sc2-units-reference | 单位目录参考 |
| sc2-localization-and-text | 本地化与文本文件 |

## 目录结构
```
.agents/skills/
  <name>/
    SKILL.md
```
每个 `SKILL.md` 含 YAML frontmatter（`name`、`description`）与正文参考。

## 安装到 WorkBuddy（使用方）
这里存的是 **源码**。要使用，把它们放到 WorkBuddy 的 skill 目录之一：
- 用户级（跨项目）：`~/.workbuddy/skills/<name>/SKILL.md`
- 项目级：`{workspace}/.workbuddy/skills/<name>/SKILL.md`

从本目录复制（或符号链接）即可，例如（Windows Git Bash）：
```bash
# 用户级
cp -r .agents/skills/* "$USERPROFILE/.workbuddy/skills/"
# 或项目级（在本 workspace 内）
mkdir -p .workbuddy/skills && cp -r .agents/skills/* .workbuddy/skills/
```
放置后重启 / 重载 WorkBuddy 对话即可触发。

也可使用本仓库沉淀的 `install-github-agent-skill` 元 skill 获取从上游重新拉取的流程。

## 安全说明
入库前已做安全审计：全部为纯文档型 `SKILL.md`，无 `scripts/` 可执行文件；唯一的可执行片段是 `sc2-localization-and-text` 中的 `sc2loc check-missing` 本地 CLI 调用（检查本地化缺失，良性）。风险等级 **P2（安全）**。

## 许可与归属
Skill 内容版权归原作者 KimPlaybit 所有（遵循上游仓库许可）。本目录仅作镜像与项目内集成，便于团队复用与版本跟踪。
