# Vibecraft 与自研合作图 AI 盟友对比评估

> 日期:2026-08-22
> 评估对象:`reference/vibecraft`(catmaniii/vibecraft @ 48b0114,MIT)vs 本工作区自研 P2 盟友体系(cmre-porting stages 05-27/50)
> 评估动机:当前合作图 AI 盟友(P2)尚未达到可用状态,评估直接采用 vibecraft 是否是更快的路。
> 证据说明:本文所有主张标注 `static`(代码/文档阅读)或 `runtime`(阶段日志中的实机验证记录);本次评估本身未启动 SC2、未运行 vibecraft 验收脚本。

## 1. 结论(TL;DR)

**vibecraft 不能直接替代当前 P2 盟友体系,原因是三个硬性架构不匹配(见 §3);但它的指令模型、仲裁机制和验收方法论确实优于自研体系,值得作为参考实现吸收。**

**达到"可用 P2 盟友"的最快路径不是引入 vibecraft 执行栈,而是在现有脊柱上补齐策略闭环**(见 §6):动作原语层已实机验证(runtime),真正缺的是全程自主驱动 P2 的策略层与事件触发通道——这两项恰好都被环境性问题阻塞,而非技术路线失败。

## 2. 两系统定位

| | 自研体系 | vibecraft |
|---|---|---|
| 解决的问题 | 合作图里 AI 扮演 P2 盟友,与人类 P1 协作 | melee 对战里 AI 替玩家操作(python-sc2 attach 自己的客户端) |
| 控制对象 | 地图原生 P2 Computer 的自定义指挥官单位 | 玩家自己的标准三族部队 |
| 游戏接入 | launcher 启动 SC2(`-listen`)+ SC2 API ws attach + Bank/raw-action 双通道 + 图内 LibVibeKernel.galaxy(`static`: `tools/galaxy-vibe/galaxy_repl.py:381,640-775`、`tools/galaxy-vibe/kernel/LibVibeKernel.galaxy:2044,2109`) | bot 侧 `SC2Process` 自建局,无 Galaxy 侧、无 attach(`static`: `reference/vibecraft/src/vibecraft/server/game_process.py:347,646-671`) |
| 目标地图 | 66 张合作图(CMRE 15 + Reborn 20 + 起义狂潮 31,`runtime`: stage 26) | 仅 DaybreakLE 调优验证(`static`: vibecraft TASKS.md 自述"方向 A") |
| 规模 | 内核 2623 行 Galaxy + 11,676 个生成 typed adapter(`runtime`: stage 26 抽样实机) | src 约 6.6 万行 + 3440 个单测 + vendored sharpy fork 3.5 万行 |

## 3. 三个硬性不匹配(直接替换不可行的依据)

1. **连接模型相反**(`static`)。vibecraft 所有路径经 python-sc2 `run_multiple_games`/`_host_game`/`_join_game` 自己拉起 SC2 进程;全库无 attach 已有进程代码。自研体系的链路是外部 launcher 建局、`galaxy_repl.py` 以 attach 方式接入 `ws://127.0.0.1:{port}/sc2api`。用 vibecraft 须重写其 server/game_process 层。
2. **引擎不支持"人 + AI 盟友"拓扑**(`static`)。vibecraft `room.py:206-216` 注明 create_game 多 agent 仅支持纯 1v1;`sc2_multiplayer.py:13-14` 注明 PlayerSetup 无 team 字段。自研体系在 stage 25 已实机验证 P1=Participant + P2=地图原生 Computer 拓扑(`runtime`)。
3. **自定义单位"看得见、指挥不动"**(`static`)。vibecraft 单位解析硬绑 python-sc2 `UnitTypeId` 枚举(`director.py:6659`),CMRE 自定义指挥官单位解析失败即丢弃;科技树/48 剧本/成本表均为标准 melee 数据。自研体系经图内 Galaxy 内核直接操作地图 catalog,Stage 21 已实机验证 21/21 采集/造兵动作、Stage 15 验证 827 次动作(`runtime`)。

## 4. vibecraft 确实上位的部分(建议吸收)

| 资产 | 位置 | 对自研体系的意义 |
|---|---|---|
| 25 种 Directive 类型 + Board 仲裁(pending→commit、来源优先级 VOICE>ABORT>BOT_INTERNAL、单位 claim 独占账本) | `reference/vibecraft/src/vibecraft/directives/`(约 1900 行,pydantic,与 SC2 传输解耦) | `tools/cmre-webui/runtime_script.py` 薄 DSL 的进化方向 |
| `done_when`/`activate_when` 条件 DSL(20 种完成条件 + any_of/all_of) | `directives/models.py:229-253` | 盟友任务/波次响应规则的建模语言 |
| 真局验收方法论:telemetry.jsonl + 多局多数票 + infra-fail 重试 | `scripts/build_acceptance.py`、47 份 spec | 反哺 stage 验证,替代单次 live smoke |
| 免 LLM 硬依赖的分层(mock-LLM JSON 环境变量 + 直连 WS JSON 通道) | `llm/config.py:112-144`、`server/ws.py:430-435` | 未来加自然语言指挥时的模式范本 |
| 手机驾驶舱 PWA + WebRTC + 语音 | `web/`、`server/webrtc.py` | 远期产品化外壳的可选项 |

明确**不可**单独抽用的:sharpy 执行栈(vendored fork 27 文件 79 处补丁,与标准 melee 经济深度绑定)——这 5 万行恰是 vibecraft "会打游戏"的部分,但对合作图 P2 无用。

## 5. 当前体系距离"可用"的真实缺口

已实机验证(`runtime`,各 stage result.json):动作原语(采集/造兵/移动/战斗)、typed task loop 6/6、P1+P2 拓扑与 `!ally` 桥、11,676 adapter 抽样 invoke。

尚未闭环(即"不可用"的实际来源):

| 缺口 | 状态 | 阻塞原因 | 性质 |
|---|---|---|---|
| 全程自主驱动 P2 的策略层 | ML 策略仅模拟器验证,native P2 由模型驱动未验证(stage 25 issue `ML-NATIVE-P2-COMPUTER-BRIDGE`) | 缺一次实机接入实验 | 技术待做 |
| 事件驱动自动行为(战斗触发规则) | BLOCKED(stage 27 issue `DOUQUQU-RUNTIME-PENDING`) | 复测时 SC2 窗口被无关会话占用,单实例无法开第二个 API | **环境性**,非技术失败 |
| Reborn 图原生开局 | BLOCKED(`MAP-COMMANDER-Reborn-RUNTIME-BLOCKED`) | zzerus03 图 CreateGame 超时 | 环境性 |
| 模拟器↔实机原生差分 | 全线 BLOCKED(stage 32/45/49) | 无 runtime 标注原生观测 | 不阻塞盟友可用性 |

结论:**基础设施(传输、内核、adapter 面)已验证可用;缺的是"大脑接入"与"事件通道开通",且两项主阻塞都是环境性的。** 换成 vibecraft 不能绕过这两项——它的"大脑"(sharpy)不懂合作图,其事件体系也构建在自建局前提上。

## 6. 路径建议

**路径 A(推荐):现有脊柱 + 策略闭环。**
1. 解锁 stage 27 事件驱动 lane(清理 SC2 单实例占用,重跑 dou-ququ runtime 复测)——Galaxy 侧触发器注册与 RuntimeConsole 分发已就绪(`static`),只差实证。
2. 把模拟器已验证的策略(Stage 19 多种子通关 / Stage 25 ML)经 `WriteModelP2Snapshot`/`ApplyModelP2Intent` 桥接入 native P2,取得一次实机全程证据。
3. 用 vibecraft 式验收(多种子多数票)定义"可用"门槛,例如"盟友在地图 X 标准难度下存活至第 N 波/完成目标"。
4. (可选,后续阶段)将 `runtime_script.py` DSL 演进为 typed directive 模型,照抄 vibecraft directives/ 设计。

**路径 B(不推荐):改造 vibecraft 直接做 P2 盟友。** 须重写 attach 层、剥离 sharpy 执行栈、重建自定义单位知识——保留的只剩 directives 包与 UX 外壳,而执行层要重做的正是自研体系已完成并验证的部分。

**路径 C(远期可选):vibecraft 壳 + 自研脊柱。** 手机驾驶舱/WebRTC/语音/LLM 解析作为前端,经 server 层适配到现有 `server.py → galaxy_repl → LibVibeKernel` 通道。仅在路径 A 达到可用、且确有移动端需求时立项。

## 7. 若立项:integration stage 轮廓

- 目标:把 vibecraft directives 模型引入 runtime_script / 策略层,或路径 C 前端适配
- writeScope 建议:`tools/cmre-webui/**`、`src/projects/cmre-porting/stages/<new-stage>/**`
- 边界:vibecraft 保持 reference/ 只读(`.gitmodules` 已注册,commit `1f1537c`),不 fork 不 vendored
- 验收:遵循 launcher 规则实机验证 + GameLogs ScriptError 复核 + runtime listener 证据

## 8. 本次评估的证据边界

- `static`:两代码库只读探查(文件引用见上文),未修改 vibecraft 任何文件。
- `runtime`:引用的实机主张均来自既有 stage result.json/log.md,本次未新产生 runtime 证据。
- `inference`:§6 路径 A 的工期判断(事件 lane 与策略接入的主阻塞为环境性)基于 issue 记录推断,需在下一阶段验证。

## 9. 决策更新(2026-08-22,用户裁决)

**用户决策:vibecraft 不是只读参考,作为后续开发的基座(fork 在其上开发)。** 本节覆盖 §6/§7 中"只读借鉴、不 fork 不 vendored"的边界;§3 的三个硬性不匹配仍是事实,但性质从"替换障碍"改为"基座上的适配工作项":

1. **attach 层**:在 vibecraft 上新增"连接 launcher 启动的既有对局"的连接模式(python-sc2 `Client` 直连 `ws://127.0.0.1:<port>/sc2api`;本工作区 `galaxy_repl.py` 已验证该模式可行),替代/并存于其 `SC2Process` 自建局路径。
2. **P2 控制缝**:vibecraft 的指令执行最终落到操作"自己玩家"的单位;适配方向是把 Director 的指令下发接到工作区已验证的 P2 通道(`WriteModelP2Snapshot`/`ApplyModelP2Intent` 或 function.invoke 面),使其驱动地图原生 P2。
3. **自定义单位知识**:把 `UnitTypeId` 硬绑的单位解析替换为工作区 function registry/catalog 数据源,使 CMRE 自定义指挥官单位可被指令引用。

**基座拉起证据(runtime,2026-08-22)**:本机 Python 3.11.9 + uv 0.12.1 满足硬锁;`uv sync --extra dev` 成功;burnysc2 因 uv git 拉取遇 GitHub 连接重置,改用 git 克隆 `august-k/python-sc2@develop` 后 `uv pip install` 装入;`pytest -m "not e2e"` **3704 passed / 64 skipped / 2 deselected**。详见 `artifacts/projects/cmre-porting/stage51-p2-ally-usability-closure/vibecraft-baseline-bringup-20260822.md`。

**仓库策略**:`reference/vibecraft` 的 `master` 保持跟踪上游原样;我们的修改在 fork 分支上进行(建议分支名 `workspace-ally`),上游同步经 git remote 完成,符合 AGENTS.md"外部工具源保持独立 Git 仓库、经文档化接口消费"的边界。适配工作建议立为独立阶段(Stage 52 候选),Stage 51 的 WP-A(事件通道)与 WP-C(P2 桥)正是该阶段的两个对接缝,先后关系不变。

