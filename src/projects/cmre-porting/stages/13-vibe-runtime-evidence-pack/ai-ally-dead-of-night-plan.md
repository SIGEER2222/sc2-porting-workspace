# AI Ally × Dead of Night Strategy Plan

> 写入时间：2026-07-31  
> 当前阶段：13-vibe-runtime-evidence-pack  
> 计划性质：下一大里程碑执行方案；不替代 Stage 13 runtime evidence gate。  
> 结论：先完成 Stage 13 真机 runtime 证据闭环，再进入 AI ally 策略升级。下一大里程碑应推进到“防守型合作 AI MVP+”，而不是追求全自动完美打穿亡者之夜。

## 1. 当前基线

### 1.1 已完成能力

- src/projects/cmre-porting/vibe/defend_policy.py 已把 DefendBasePolicy 从 simulator runner 中正式模块化，目标是让 simulator runner 与 live runner 直接 import 同一套策略逻辑。证据：defend_policy.py:1-6。
- 当前策略已有基础动作模型：DefendAction 支持 attack、hold、move、gather、train、build，并带 reason 字段，适合扩展为可解释决策树。证据：defend_policy.py:24-33。
- 当前策略已有基础优先级：基地威胁、近距威胁、低血量后撤、SCV 经济、战斗单位生产、SCV 训练、默认防守。证据：defend_policy.py:62-73。
- 当前经济层已有每帧 reserve 池，避免 SCV 训练抢光战斗单位资源。证据：defend_policy.py:36-59、defend_policy.py:228-346。
- 当前配兵层已有 dict 化目标比例与优先级，使用 SiegeTank、Medivac、Marine、Marauder 的 Terran/Raynor 风格防守组合。证据：defend_policy.py:84-96。
- live runner 已实现 SC2 API 链路：CreateGame -> JoinGame -> Observation -> DefendBasePolicy -> Action，并显式处理 ActionResult.Success=1。证据：run_dead_of_night_live.py:4-12、run_dead_of_night_live.py:530-697。
- Stage 12 已生成 Dead of Night manifest/scenario/tasks/runtime recipe/.vtest，并把 live runtime 明确标为 runtime-pending，没有把 simulator 证据冒充为 runtime。证据：src/projects/cmre-porting/stages/12-vibe-task-manifest/result.json、artifacts/projects/cmre-porting/stage12-vibe-task-manifest/manifest.json。
- Stage 08 后续问题中 AI-ALLY-LIVE-001 已 resolved，3500 loop live test 记录为 verdict=victory、2034 dispatched、1177 success、无 ScriptError。证据：src/projects/cmre-porting/stages/08-final-acceptance/issues.json、src/projects/cmre-porting/artifacts/vibe-live-test/20260731-150000/live-report-3500.json。

### 1.2 当前不能宣称的能力

- 不能宣称“亡者之夜完整 AI 队友已完成”：当前 live 证据证明 API 闭环和短程稳定性，不证明完整 day/night mission loop、长期资源扩张、阵地移动和多波次战术都可靠。
- 不能把 Stage 12 runtime-pending 改写为 runtime PASS：Stage 13 仍需通过合规 launcher 执行 .vtest，并复核本次启动新增 ScriptError。
- 不能把外部开源 bot 框架作为直接依赖引入本项目：本阶段只借鉴设计模式，保持 defend_policy.py 轻量、无 simulator/live 专属依赖。

## 2. 下一大里程碑定义

### 2.1 推荐目标

把 SC2 simulator + AI ally + 亡者之夜 推进到：

**防守型合作 AI MVP+**

具体含义：

1. 同一套 DefendBasePolicy 能在 synthetic policy tests、Dead of Night simulator、live SC2 runner 三层运行。
2. 决策不再只是“发现敌人就 attack，否则 hold”，而是具备可解释的状态机/决策树：
   - phase：开局经济、夜间防守、受袭应急、恢复经济、供应/生产受阻；
   - threat：基地内威胁、近距威胁、远距威胁、无威胁；
   - posture：hold、engage、retreat、recover、macro；
   - reason：每个动作都能解释来自哪个分支。
3. 经济不再只靠单次 reserve 池，而是具备可观测的 macro scheduler：
   - SCV floor/ceil；
   - combat reserve；
   - supply block handling；
   - producer queue awareness；
   - gas/producer 缺失时的降级训练。
4. 配兵不再固定比例，而是按 phase/threat 动态调整：
   - 早期：Marine 优先，保证廉价 DPS 与 command coverage；
   - 中期：Tank/Medivac 权重提升，增强阵地防守与续航；
   - 空中/特殊威胁出现时：Viking 或可用反空 fallback；
   - gas/producer 不足时：不因高阶兵种缺资源而停产，必须 fallback 到 Marine/SCV/供给动作。
5. 战术不再只按单兵最近目标：
   - squad-level target selection；
   - low HP retreat；
   - worker panic/return-to-work；
   - base anchor/rally；
   - 重复命令抑制；
   - threat priority：基地内 > 工人附近 > 生产建筑附近 > 普通近距。
6. 验收必须包含可人工审阅的“时间轴小地图回放包”，让用户能像看小地图一样快速判断 AI 行为是否合理，而不是只看 JSON 数字。
7. 真机验收仍采用 launcher + ScriptError gate，不直接启动 SC2_x64.exe。

### 2.2 非目标

- 不在本里程碑追求完整自动清图、最优建造序列、所有指挥官泛化、复杂协同进攻或 RL/LLM 决策。
- 不在本里程碑修改 canonical commander mod 或 map-owned mission script，除非 Stage writeScope 明确授权。
- 不引入 python-sc2、ares-sc2、PySC2 为运行时依赖；它们只作为设计参考。

## 3. 外部参考如何使用

仅做模式借鉴，不做依赖引入：

- Ares SC2 的 ProductionController / SpawnController 使用 army composition dict 与 priority/proportion 控制生产；这与当前 ARMY_COMP 的方向一致，后续可借鉴其 “composition profile + macro plan priority” 结构。
- Ares SC2 的 MacroPlan 将 supply、worker、gas、spawn、production 以优先级串起来；后续可把当前 _decide_economy() 拆成可测试的 macro lanes。
- python-sc2 的 action 模型强调 cost/supply 扣减、same-frame duplicate command suppression、worker selection/build placement；后续可借鉴到 producer queue、资源预留和 supply block 测试。
- PySC2 的价值主要是 observation/action environment 概念与 replay/visual debugging 参考；本项目已有自有 simulator/live API runner，暂不需要迁移。

## 4. 执行阶段

### Phase 0：完成 Stage 13 runtime evidence gate

目的：先把 Stage 12 的 runtime-pending contract 变成真实 runtime evidence，避免策略升级建立在未闭环的运行时基础上。

工作：

1. 使用 tools/galaxy-vibe/launch-galaxy-vibe.ps1 执行 artifacts/projects/cmre-porting/stage12-vibe-task-manifest/scenario.vtest。
2. 依赖 launcher ready signal，不固定时间盲等。
3. 收集 launcher output、assertion/verdict、ScriptError check、evidence bundle。
4. 若 live runtime 不可用，记录 blocked-runtime-unavailable，不要用 simulator 或 stub 替代 runtime。

验收：

- src/projects/cmre-porting/stages/13-vibe-runtime-evidence-pack/result.json 记录 runtime verdict 或 blocked reason。
- log.md 记录命令、时间窗、ScriptError 路径、证据分类。
- issues.json 关闭或保留 VIBE-RUNTIME-EVIDENCE-001。

### Phase 1：策略可观测与测试底座

目的：先锁住当前行为，防止升级决策树时破坏已通过的 live/simulator 闭环。

工作：

1. 为 DefendBasePolicy.decide() 输出 decision summary：
   - loop；
   - phase；
   - threat level；
   - economy lane decisions；
   - actions by reason；
   - skipped reasons（supply blocked、no producer、cannot afford、cooldown）；
   - replay event markers（night start、wave spawn、base breach、retreat、train burst、supply block、recovery）。
2. 新增 synthetic observation builder，覆盖无需启动 SC2 的策略单测。
3. 将 reason 字段规范化为稳定枚举式字符串，便于断言。
4. 定义 replay frame schema，让 simulator/live runner 都能输出同构的时间轴事件与小地图帧数据。

验收：

- python -m py_compile src/projects/cmre-porting/vibe/defend_policy.py src/projects/cmre-porting/vibe/run_dead_of_night.py src/projects/cmre-porting/vibe/run_dead_of_night_live.py PASS。
- synthetic policy tests 至少覆盖：
  - base threat -> combat attack + worker retreat；
  - near threat -> combat attack；
  - low HP without base threat -> retreat；
  - idle SCV -> gather/hold transition；
  - no enemy -> hold base；
  - economy reserve prevents SCV starving combat unit；
  - no gas/no advanced producer -> Marine fallback；
  - producer already commanded -> no duplicate train in same decision frame。
- 每个测试断言 action kind、target/reason、resource reservation side effect。
- policy test artifact 必须能生成至少 3 个 replay marker 样例：威胁出现、AI 响应、经济/训练动作。

### Phase 2：决策树 / 状态机

目的：把当前平铺优先级升级为 inspectable decision tree。

工作：

1. 新增 lightweight policy state：
   - phase: opening, night_defense, under_attack, recovering, macro_idle；
   - threat_level: none, near, base, critical；
   - econ_pressure: normal, low_workers, supply_blocked, gas_blocked, producer_blocked。
2. 将 threat classifier 从 decide() 中抽出：
   - base center / production structures / worker cluster 三类 anchor；
   - enemy distance、target type、己方损伤作为 scoring factors。
3. 将 action selection 改成：
   - classify -> choose posture -> emit tactical actions -> emit macro actions。

验收：

- 决策树每个 branch 有至少一个 synthetic test。
- 3500 loop simulator run 的 replay/summary 中 action reasons 覆盖 base_threat、near_threat、defend_base、gather_minerals、train_* 至少 5 类。
- 重复运行同 seed 输出稳定：总命令数、waves fired、survivors 在允许阈值内无异常波动。

### Phase 3：经济 / 生产调度

目的：让 AI 队友在亡者之夜防守中不会陷入“只造农民”、“只攒高阶兵”、“供应卡死”、“有建筑不用”四类常见失败。

工作：

1. 将 _decide_economy() 拆成 lanes：
   - worker lane；
   - supply lane；
   - gas lane；
   - combat production lane；
   - recovery lane。
2. 引入 macro priority order：
   - emergency worker floor；
   - supply unblock；
   - immediate defense production；
   - worker ceil；
   - tech / advanced composition。
3. 记录 skipped macro reasons：
   - skip_supply_ok；
   - skip_no_idle_producer；
   - skip_cannot_afford_reserved；
   - skip_missing_prereq_or_producer。
4. 保持资源逻辑为 local reservation，不硬编码 live runner 或 simulator internals。

验收：

- supply remaining <= 1 且资源足够时，策略输出 supply/build 或明确 supply_blocked_no_builder reason。
- 有 Barracks 且 gas 不足时，不能因为 Tank/Medivac 资源不足而停止 Marine 训练。
- SCV 低于 floor 时可抢占资源恢复经济；达到 ceil 后不再抢战斗单位资源。
- 同一 producer 在同一 decision frame 最多收到一个 train/build action。

### Phase 4：动态配兵

目的：让配兵目标由固定 dict 变为 phase-aware composition profile。

工作：

1. 定义 composition profiles：
   - opening_defense: Marine-heavy；
   - night_hold: Marine + Tank；
   - sustain: Tank + Medivac；
   - anti_air_or_special: Marine/Viking fallback；
   - low_resource_fallback: Marine/SCV/supply only。
2. 根据 threat/phase/economy 选择 profile。
3. 对缺失 producer/gas/supply 的 profile 降级，而不是空转。

验收：

- profile selector synthetic tests 覆盖 opening、base threat、gas blocked、producer missing、supply blocked。
- 每个 profile 输出的目标比例和实际 train reasons 可在 summary 中看到。
- simulator 3500 loop 不出现连续 10 个经济 tick 无有效 macro action 且无明确 skipped reason 的情况。
- simulator 3500 loop 必须产出 replay review artifact，包含关键时间点的小地图帧和事件摘要。

### Phase 5：战术与队伍行为

目的：从单兵最近目标推进到“防守阵地 + 小队交战 + 低血量撤退”。

工作：

1. 建立 squad classifier：
   - combat units；
   - workers；
   - producers/static defense；
   - medics/medivacs/support。
2. 建立 target scoring：
   - base threat 权重最高；
   - worker cluster threat 次之；
   - production structure threat 次之；
   - low HP enemy / closest enemy 作为 tie-breaker。
3. 对低血量单位和支援单位使用 retreat/rally，而不是继续冲锋。
4. 对无威胁状态使用 defend anchor / rally point，而不是全员重复 hold。

验收：

- synthetic combat tests 覆盖 target priority、retreat、worker panic、support rally。
- replay summary 中低血量单位产生 retreat_low_hp，并且 base threat 场景不会触发错误后撤导致基地失守。
- live smoke 中 action success rate 不低于当前 3500 loop 基线的 57.9%，或若下降则必须有明确 unsupported command / map state 解释。

### Phase 6：三层验收

目的：每次策略升级后都能证明“策略正确、模拟稳定、真机可运行”。

#### 6.1 Static / policy gate

命令：

    python -m py_compile src/projects/cmre-porting/vibe/defend_policy.py src/projects/cmre-porting/vibe/run_dead_of_night.py src/projects/cmre-porting/vibe/run_dead_of_night_live.py

通过标准：

- py_compile PASS；
- policy synthetic tests PASS；
- JSON/report artifacts 可解析；
- 无新增 TODO 作为验收替代。

#### 6.2 Simulator gate

建议命令：

    $env:PYTHONPATH='src/projects/cmre-porting'
    python -m vibe.run_dead_of_night --max-loops 1500 --include-preset-enemies --output artifacts/projects/cmre-porting/stage14-ai-ally-strategy-upgrade/sim-1500.json
    python -m vibe.run_dead_of_night --max-loops 3500 --include-preset-enemies --output artifacts/projects/cmre-porting/stage14-ai-ally-strategy-upgrade/sim-3500.json

通过标准：

- 两次 run 均无异常退出；
- verdict 为 victory 或 inconclusive-survived，不得为 defeat；
- player survivors > 0；
- waves fired > 0；
- commands issued/dispatched > 0；
- action reasons 覆盖战斗、经济、训练、撤退/防守；
- 无连续经济死锁：连续 10 个 econ tick 不得全是空动作且无 skipped reason。

#### 6.3 Live SC2 gate

启动规则：

    pwsh -NoProfile -ExecutionPolicy Bypass -File .\tools\launchers\launch-cmre-alenger.ps1 -MapName '亡者之夜.SC2Map' -Commander 'TerranRaynor' -ListenPort 5000 -KeepAlive

runner：

    $env:PYTHONPATH='src/projects/cmre-porting'
    python -m vibe.run_dead_of_night_live --port 5000 --map "E:\SC2\SC2new\StarCraft II\Maps\亡者之夜.SC2Map" --max-loops 1500 --output artifacts/projects/cmre-porting/stage14-ai-ally-strategy-upgrade/live-1500.json

升级后长烟测：

    $env:PYTHONPATH='src/projects/cmre-porting'
    python -m vibe.run_dead_of_night_live --port 5000 --map "E:\SC2\SC2new\StarCraft II\Maps\亡者之夜.SC2Map" --max-loops 3500 --output artifacts/projects/cmre-porting/stage14-ai-ally-strategy-upgrade/live-3500.json

通过标准：

- 必须通过 tools/launchers/launch-cmre-alenger.ps1，禁止直接启动 SC2_x64.exe。
- launcher ready signal 成功，不能固定时间盲等。
- 本次启动时间窗内无新增 ScriptError.*.txt；若有新增，必须记录为 FAIL/open issue。
- CreateGame/JoinGame/Observation/Action 链路成功。
- 1500 loop smoke PASS 后才执行 3500 loop。
- 3500 loop 满足：
  - no crash；
  - no ScriptError；
  - commands dispatched > 0；
  - action success rate 不低于 55%，或下降原因可解释；
  - final player survivors > 0 或 objective/game result 能解释非 defeat；
  - artifact 中包含 decision summary。

#### 6.4 Replay / minimap review gate

目的：让验收从“机器报告 PASS”升级为“人能判断是否合理”。每次 1500/3500 loop simulator 与 live smoke 都必须生成一个轻量 replay review pack，展示关键时间节点的小地图态势、AI 决策和结果。

必须产出：

- replay.jsonl：逐帧或抽样帧数据，至少包含 loop、game_time、phase、threat_level、own_units、visible_enemies、commands、action_reasons、resources、supply、wave_id。
- timeline.json：关键事件索引，按时间排序，至少包含 event_type、loop、position、summary、policy_reason、before/after metrics。
- minimap frames：小地图式静态帧，可为 SVG/PNG/HTML 任一格式；每帧必须标注：
  - 玩家基地 / 防守 anchor；
  - 敌方波次或威胁位置；
  - 己方主力 / 工人 / 生产建筑；
  - AI 下达的 attack / move / retreat / train / build 事件；
  - 资源、人口、存活单位、当前 phase/threat_level。
- review.html 或 review.md：人类审阅入口，按时间轴串起关键帧，能直接看出“为什么 AI 在这个时间点这么做”。

关键时间节点至少包含：

1. game start / first economy tick；
2. first worker/gather decision；
3. first combat production decision；
4. first wave spawned；
5. first enemy near base；
6. first base threat or breach；
7. first retreat_low_hp；
8. first supply block / unblock（若发生）；
9. first composition profile switch；
10. final 30 秒或 final 300 loops。

通过标准：

- 1500 与 3500 simulator run 均生成 review pack。
- live 1500 与 live 3500 smoke 均生成 review pack；若 live observation 缺少某些坐标字段，必须在 review 中标注为 missing-data，而不是静默省略。
- timeline 中每个关键事件都能映射到至少一个 minimap frame。
- minimap frame 上必须能肉眼看到敌我相对位置、基地/anchor、AI 目标点或目标单位。
- review artifact 必须包含“AI 行为合理性摘要”，至少回答：
  - 是否及时防守基地；
  - 是否错误追远离基地的目标；
  - 是否在低血量时后撤；
  - 是否在供应/资源受阻时有合理 fallback；
  - 是否存在长时间空转或重复命令刷屏。
- 完成汇报时不只报 verdict，还要附 replay review artifact 路径；用户可以据此人工判断策略是否合理。

## 5. Stage 14 建议切分

Stage 13 关闭后，建议创建：

src/projects/cmre-porting/stages/14-ai-ally-strategy-upgrade/

建议 writeScope：

- src/projects/cmre-porting/project.json
- src/projects/cmre-porting/stages/14-ai-ally-strategy-upgrade/**
- src/projects/cmre-porting/vibe/defend_policy.py
- src/projects/cmre-porting/vibe/run_dead_of_night.py
- src/projects/cmre-porting/vibe/run_dead_of_night_live.py
- tests/** 或现有 simulator test 目录中与 policy 相关的测试文件
- artifacts/projects/cmre-porting/stage14-ai-ally-strategy-upgrade/**

建议 outputs：

- plan.md
- log.md
- issues.json
- result.json
- policy synthetic test report
- simulator 1500/3500 reports
- live 1500/3500 reports
- ScriptError check report
- replay/decision summary jsonl
- replay review pack：timeline.json、minimap frames、review.html 或 review.md

## 6. 里程碑完成判定

本里程碑完成时，可以对外宣称：

> “亡者之夜 Terran/Raynor 防守型 AI 队友 MVP+ 已完成：同一策略模块通过 synthetic policy tests、Dead of Night simulator 1500/3500 loop、live SC2 launcher/API 1500/3500 loop；具备可解释决策树、资源 reserve/macro scheduler、动态配兵 profile、基础 squad tactical behavior；产出可人工审阅的时间轴小地图回放包，并且无新增 ScriptError。”

仍不能宣称：

> “AI 已能完整最优通关亡者之夜” 或 “适配所有地图/所有指挥官”。

## 7. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| Stage 13 runtime gate 未关闭 | 后续策略缺少真实 runtime 基线 | 先执行 Stage 13；若 blocked，记录 blocked-runtime-unavailable，不推进 live PASS 宣称 |
| AI 策略越来越复杂但不可测 | 后续调参会回归 | 每个 branch 必须 synthetic test + reason summary |
| 高阶兵种优先级导致 Marine 停产 | 前期防守崩溃 | profile fallback + reserve/skipped reason 断言 |
| 供应卡死但无动作 | 长跑死锁 | supply lane + supply_blocked tests |
| simulator 与 live observation 差异 | 模拟通过但真机失败 | live runner decision summary 与 action result 分类必须进入 artifact |
| 只有数字报告，用户无法判断策略是否合理 | 验收不可信 | replay review pack 必须包含时间轴、关键帧、小地图标注、行为合理性摘要 |
| 直接启动 SC2 绕过保障 | 无法判断 runtime 证据有效性 | 只用 tools/launchers/，并复核新增 ScriptError |

## 8. 推荐停止点

做到以下程度就算“比较大的里程碑”，可以向用户汇报并暂停：

1. Stage 13 runtime evidence 已关闭或明确 blocked；
2. Stage 14 策略升级实现完成；
3. synthetic policy tests PASS；
4. simulator 1500/3500 PASS；
5. live 1500/3500 PASS；
6. replay review pack 可打开，且包含 timeline、minimap frames、关键事件标注、行为合理性摘要；
7. no new ScriptError；
8. result.json、issues.json、log.md 全部更新；
9. 下一阶段计划写明是继续完整 30k loop/全天夜循环，还是扩展到进攻/清图/多指挥官。
