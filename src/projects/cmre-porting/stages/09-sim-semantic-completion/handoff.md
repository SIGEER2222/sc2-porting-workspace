# Stage 09 Handoff: sc2_simulator 当前进度与剩余项

> 更新时间：2026-07-31T20:55:00+08:00  
> 范围：Stage 09 收口后的交接说明；不扩展真实 SC2 / Bank / Galaxy 传输通道。

## 1. 当前方案

- static+runtime: 当前主线是 simulator-first：以 reference/sc2-ally-bot/src/sc2_simulator 作为本地确定性 headless 规则运行时。
- static: 真实 SC2 / Bank / MapCommand / Galaxy transport 仍作为可选 P9 校准路径，不阻塞本地 P0-P8 和 simulator 回归。
- static: CMRE 项目侧的 Vibe adapter 继续承载任务/区域/波次/契约层兼容逻辑；只有当多个真实消费者需要同一能力时，再考虑下沉到 simulator core。

## 2. 已完成进度

- runtime: Stage 09 已关闭 SIM-CAP-GAP-006：Overlord 飞行属性下沉到 m3 源 Catalog，m7 不再靠专门补丁兜底。
- runtime: Stage 09 已关闭 SIM-CAP-GAP-007：instant/projectile splash 次目标现在按自身 armor / attributes / behaviors 重算 damage breakdown。
- runtime: tests/sc2_simulator 全量回归通过：448 passed。
- runtime: targeted regression 通过：Overlord source catalog flying 测试 + Hellion splash 次目标护甲重算测试。
- static: Stage 08 final acceptance 已 PASS；AI-ALLY-LIVE-001 已有 3500 loop 真机闭环证据并标记 resolved。

## 3. 真正还差的项

| 优先级 | Issue | 状态 | 还差什么 | 是否阻塞 simulator 主线 |
|---|---|---|---|---|
| P1 | AI-ALLY-LIVE-002 | open | ActionResult.Success=1 统计修正后，用合规 launcher 重跑 live smoke，并复核新增 ScriptError.*.txt | 否，仅阻塞 live 证据刷新 |
| P2 | CATALOG-M3-ZERG-THIN-001 | open | m3 Zerg 层仍偏薄；Overlord 已修，但 Zergling/Baneling/Roach/Hydralisk/Mutalisk 等仍主要靠 m7 补齐 | 否，m7 当前可跑 |
| P2 | CATALOG-UPGRADE-EFFECTS-001 | open | 为 UpgradeType.effects 建静态引用闭包校验：UnitId、字段路径、删除/重命名引用 | 否，属工具链硬化 |
| P3 | CATALOG-COVERAGE-MAP-001 | open | 接入 catalog coverage 自动报告，统计 m1-m7 合并后单位/建筑/英雄覆盖率 | 否，属可观测性改进 |

## 4. 账本待整理项

这些不是当前功能缺口，但历史阶段文件还有陈旧状态；由于不在 Stage 09 writeScope，本阶段未直接改写。

- static: Stage 05 issues.json 仍把 SIM-CAP-GAP-002/003 记为 open；实际 Stage 06 已修复，应在后续账本整理阶段标记为 resolved-fixed-later 或增加 Stage 06 cross-reference。
- static: Stage 06 issues.json 仍把 SIM-CAP-GAP-006/007 记为 open；实际 Stage 09 已修复，应在后续账本整理阶段标记为 resolved-fixed-later 或增加 Stage 09 cross-reference。
- static: Stage 08 catalog-issues.json 的 CATALOG-BOUNCE-001 测试证据仍写 446/446；Stage 09 后当前 simulator 回归为 448/448，后续可补记。

## 5. 推荐下一阶段

建议新开 10-post-acceptance-hardening，writeScope 明确包含：

- src/projects/cmre-porting/stages/05-vibe-framework/issues.json
- src/projects/cmre-porting/stages/06-sim-cap-completion/issues.json
- src/projects/cmre-porting/stages/08-final-acceptance/catalog-issues.json
- src/projects/cmre-porting/stages/08-final-acceptance/issues.json
- src/projects/cmre-porting/stages/10-post-acceptance-hardening/**

阶段目标：

1. 只做历史账本 reconciliation，不改 simulator 行为。
2. 如需继续技术硬化，优先做 UpgradeType.effects 静态闭包校验和 catalog coverage 报告。
3. 如要关闭 AI-ALLY-LIVE-002，必须遵守 launcher 规则启动 SC2，不直接运行 SC2_x64.exe，并复核本次启动新增 ScriptError。

## 6. 工作区注意事项

- static: Stage 09 相关变更集中在 reference/sc2-ally-bot/src/sc2_simulator/**、对应 tests、Stage 09 文档和 Stage 07 issue 更新。
- static: 当前工作区还有 Galaxy/Vibe/live artifacts 的既有 dirty changes；它们不属于 Stage 09 simulator semantic fix，提交时建议拆分。
- inference: 推荐至少拆成两个提交：一个提交 simulator semantic fixes + tests；一个提交 cmre stage docs / handoff。Galaxy/live 改动另行审计后再处理。
