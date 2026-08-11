# 双模块进度与推进计划（automation-1786147851662 · 2026-08-10 05:xx 自动轮次）

> 范围：① sc2 mod vibe 能力（galaxy-vibe 运行时 VM）② 起义狂潮地图移植 C（RevolutionOverdrive porting C）。
> 任务：自动总结进度 + 输出 plan + 继续推进（"自行测试和验证" + "允许直接重启游戏"）。

---

## 一、本轮执行摘要

- **离线 7 道门禁 fresh 全绿（实跑）**：static-validate PASSED；galaxy-lint cmre **0 error** + RO **0 error**；test_kernel **59 passed**；RO ally **43 passed**；CMLib gate **ALL PASSED**（typecheck 0）；run-all-validation **全 PASS / 0 FAIL**。
- **真机线解阻塞 + Module 1 真机复验闭环**：菜单态 SC2（PID 31200，仅 :6119）→ kill + `SC2Switcher_x64 -listen 127.0.0.1 -port 5000 -debug` 重启 → 新 PID 38208 绑 :5000 + :6119。重建 gen 图（注入**当前工作区内核 03:38**，sha `merged_fix=5`，16/16 静态门禁 `[DONE]`）→ `tier100_live_probe` 首连 `Server disconnected`（headless 对话框挡 ws 的瞬时态），实例静置后重试 **tier100_pass=true**：
  - Kernel 已注册、system.ping 1/1 ack、vibe.unit.spawn +1 Marine（SC2 raw observation 实证 0→1）、query.units 自查一致、gen.1(AIAbilityFixed 只读 catalog 查询) + gen.202(AIGetNumTeams) 经 function.invoke 派发到**真机原生**成功、**0 ScriptError**、errors=[]。
  - → **当前 WIP 内核经真机背书，Module 1 运行时能力闭环保持**。
- 证据：`artifacts/galaxy-vibe/tier100-live-verdict-wip3.json`（map_bytes=5537191）。
- ⚠️ 关键回填：gen 图 `C:/tmp/VibeDeadOfNight-Gen.SC2Map` 时间戳 01:48 **陈旧**（工作区内核 03:38），直接探针验证的是旧内核。必须在探针前用 `mpq_inject_workspace_kernel.py` 注入当前内核重建图，否则真机验证失真。
- 🔴 **重建 gen 图时基底必须是 gen 血统**（2026-08-10 06:xx 事故补录，上一条指引未写基底即事故直接诱因）：
  ```
  python tools/galaxy-vibe/mpq/mpq_inject_workspace_kernel.py \
      C:/tmp/VibeDeadOfNight-Gen-k004.SC2Map  C:/tmp/VibeDeadOfNight-Gen.SC2Map
  ```
  **绝不可拿 `C:/tmp/VibeT4.sc2map` 当基底**（那是"生成 VibeT5"的纯内核实验基底，也是该脚本的旧默认值）。
  VibeT4 血统的 MapScript 同样 `include "LibVibeInvokeDispatch_active"`，却缺 `VIBE_FORWARD_PROTOS`
  前向原型区 → invoke 层引用 MapScript 本体函数（`gf_*`/`auto_gf_*_TriggerFunc`/`gt_*_Func`）无声明
  → 编译失败 → **SC2 静默丢弃整个 MapScript**。真机表现是 `kernel_registered=false` + **0 ScriptError**，
  极像内核 Bank 逻辑回归，实则基底错（本轮已因此误诊一整轮）。
  识别法：gen 血统 **5.4MB+**，VibeT4 血统 4.65MB；MapScript md5 `bfdd68d5…`(376519B) vs `5a33a542…`(357189B)。
  该脚本现已 **fail closed**（删除默认基底）并内置前置血统门禁 + 后置断言（自检 16→17 项），
  守护测试 `tools/galaxy-vibe/tests/test_map_lineage_gate.py`（8 passed，含 VibeT4 反向对照）。

---

## 二、双模块状态

### 模块一：sc2 mod vibe 能力（galaxy-vibe 运行时 VM）
- **核心能力闭环**：Kernel 注册 / Bank RPC 通道（system.ping→response pong）/ unit.spawn 经 SC2 raw observation 回读 / function.invoke 派发 gen.* 原生能力（口径 **11676 gen / 11696 total**）/ RPC 库 `GalaxyVibe` 与模型库 `GalaxyVibeModel` 分库（VIBE_GEN_007 治本）/ 内核修复 VIBE-KERNEL-002(PollLoop 读取顺序) / -003(哑拒绝补出口) / -004(watchdog 心跳改走模型库消除 Bank 抹除 → p95 长尾 4904→778ms)。
- **口径 closed**（Stage26 LIVE-PASS 全绿，多实例已复验）。Neuro G4 = **6 绿 1 红 PARTIAL**：残留 ~1% Bank 有损底噪 `HANDLER_ABORTED` + 单样本超 15s 窗，**诚实留为开放性能项，全程未放宽判据**。
- **CMLib round25 闭环**：AIFilter 族结案（7 转正封装 + 1 幽灵 + 1 拒绝）+ 原生台账门禁 `check_native_ledger.py`（9 关 ALL PASSED）；三档真机 内联 556/556 · 依赖挂载 556/556 · 反向 FAIL；产物 `CMLib_out.SC2Mod` 277335B。

### 模块二：起义狂潮地图移植 C（RevolutionOverdrive porting C）
- **源目录在盘**：`C:\Users\22448\Downloads\RevolutionOverdrive缝合版\RevolutionOverdrive缝合版`（8 mod + 31 map + launch-ro.ps1，本轮 `ls` 确认）。
- **Stage 08 closed**（P2 真机手授权获得 1 个 Odin，仅用 Debug.game_state.god，无地图编辑/P2 单位注入/通用 melee AI）；**Stage 09**（runtime-retry 静态完成，RO-RUN-010 真机 lease 阻塞）；**RO-AI-001 闭环**（182 进合约 + 18 fail-closed 审计钉死 `runtime_leader_identity`）。
- **离线 43 passed**（含 Stage09 测试）零回归；galaxy-lint RO **0 error**。
- 无遗留不泛化项。

---

## 三、本轮自测证据表

| 门禁 | 命令 | 结果 |
|---|---|---|
| static-validate cmre-porting | `node tools/analysis/static-validate.mjs cmre-porting` | **PASSED** (2 passed / 0 failed / 2 warn) |
| galaxy-lint cmre | `node tools/analysis/galaxy-lint.mjs src/projects/cmre-porting` | **0 error** (34 warn / 628 sugg) |
| galaxy-lint RO | `node --max-old-space-size=8192 tools/analysis/galaxy-lint.mjs src/projects/revolution-overdrive-porting` | **0 error** (40 warn / 81 sugg) |
| test_kernel | `pytest tools/galaxy-vibe/tests/test_kernel.py` | **59 passed** |
| RO ally | `pytest src/projects/revolution-overdrive-porting` | **43 passed** |
| CMLib gate | `python src/lib/gate.py` | **ALL PASSED** (typecheck errors=0) |
| run-all-validation | `pwsh tools/galaxy-vibe/run-all-validation.ps1` | **全 PASS / 0 FAIL** |
| tier100 真机 | `tier100_live_probe --map <WIP重建图> --fresh-bank --port 5000` | **tier100_pass=true** |

- **唯一非绿（设计内 / 诚实缺口）**：Stage 25 `test_p1_ml` 1 failed = 缺 live 人类 P1 观测 jsonl，非回归，不得降 skip。
- cmre-rl 套件（Module 2 训练线）前序轮 **234 passed**，本轮未重跑（WIP 改了 `run_live_rl.py` 等但属 N5b route B 接线，非模块核心回归面；如需可补跑）。

---

## 四、推进计划（P0–P4）

- **P0（本轮已完成）**：双模块离线门禁复绿 + Module 1 真机 tier100 复验闭环 + gen 图重建纪律回填。
- **P1（Module 1 G4 残余 1 红）**：抓修 ~1% `HANDLER_ABORTED` / 单样本超窗。`bank_request_landed` 候选分叉/陈旧让 at-least-once 补发持续落空（与 ~1% 底噪疑似同源）。静态+真机 n=100 p95 复测，目标把红项收敛或钉死为固有底噪。
- **P2（Stage 25 人类 P1 证据）**：需 live SC2 + 真人在 UI 打 P1（沙箱不可代打），诚实红条保留。
- **P3（git 收尾）**：159 WIP 未提交（含本轮 gen 图 WIP 重建产物 + tier100 证据 + 多 galaxy-vibe 源码改动）。按 C-lite 纪律精确 `add` 真实源码改动，不盲提交子模块 gitlink / 派生目录（`src/lib/` / `build/` / `.cache/` 已 gitignore）。
- **P4（低优先）**：header 分叉统一；filter-repo 瘦身（破坏性重写 + 强推，待显式授权）。

---

## 五、诚实未决 / 证据缺口

1. **Stage 25 manual-p1 观测文件缺失** —— 用户侧 live 动作，非代码缺陷。
2. **Module 1 G4 残余性能红** —— 非阻塞，已钉死为 Bank 有损底噪 + 单样本超窗；P1 收敛中。
3. **159 WIP 未提交** —— 含本轮真机证据 + WIP gen 图；git 0/0 同步但工作树漂移。
4. **真机环境头leness对话框** —— headless 首启/重启后对话框挡 ws，需静置后重试（本轮 3 连击第 3 次才过；首次 `Server disconnected` 不直接判 env-blocked）。

---

## 六、结论

双模块沙箱可验证部分 + Module 1 真机运行时**均全绿**；Module 2 收口（Stage 08/09 + RO-AI-001）。唯一实质阻塞 = Stage 25 人类 P1 证据（用户侧）与 git 提交纪律（待授权精确提交）。本轮改动（gen 图 WIP 重建 + tier100 证据 json）**未提交**。
