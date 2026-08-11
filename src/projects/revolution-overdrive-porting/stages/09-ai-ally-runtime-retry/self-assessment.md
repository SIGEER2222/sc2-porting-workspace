# Stage 09 Self-Assessment

> 2026-08-09 重写。上一版声称"运行时观测契约 5/5 通过"，那套实现已随 C-lite 收口回退、
> 仓库中并不存在，该声明失真，现整体作废。

## Result

**Native P2 handover observed. Stage 09 passed.**

不是"适配层新增了能力"，而是 Stage 09 本来的目标达成了：拿到一个稳定、无 debug 的原生窗口，
跑未经修改的 Stage 08 护送探针，看地图自己把 Odin 交给 P2。

## Proven

- 完整生命周期：`CreateGame=init_game`(nested_error=0) → `JoinGame=in_game`(player 1) →
  catalog 12225 abilities → 观测从 loop 88 推进到 1465。
- 交接是地图自身行为：Tychus 于 loop 939 以原生 P1 指令进入 Region 24；Odin
  `tag 4294967297` 于 loop 1273 由 `owner=16/alliance=3`（可救援中立）变为
  `owner=2/alliance=2`。**同一个 tag 换手**，不是凭空出现一个新单位。
- `alliance=2` 来自 P1 自己的 observation，即"P2 是我的盟友"这件事是被观测到的，不是被推断的。
- 未被制造：`map_edits=false`、`adapter_created_p2_units=false`、
  `generic_melee_ai_injected=false`、`debug_apis_used=[]`。
- 同窗口 GameLogs 零 `*ScriptError*.txt`。
- 该证据现由 9 条离线断言锁形（不需要 SC2 即可复验），项目套件 32 → 43 passed。

## Not proven

- **RO-AI-001 没有因此收敛。** 一次 rescue 交接给出的是*单位归属*，不是
  PlayerGroupLoop 的*领袖身份*。18 条 `runtime_leader_identity` 仍然 fail-closed，
  182 条具体边仍在合约内。把这次窗口当作 RO-AI-001 的证据会是过度声明。
- `p2_has_active_orders=false`：观察窗内没有捕捉到 P2 的主动指令。这只说明 192 loop 的
  观察窗太短或该时点 AI 无动作，**不构成** "P2 不会行动" 的结论；要下这个结论需要更长窗口。
- 本轮只覆盖 `thorner03` 一张图。其余 30 张图的原生交接未被验证。

## Self-critique

三件事值得记下来：

1. **我把"blocked"的归因搞错了一轮。** 上一轮把 Stage 09 记成"被外部 SC2 lease 阻塞"，
   于是本轮开局就去清进程、搬 604MB 的 mod、补整条依赖链——全都没用。真因是探针和地图不是同一张图：
   探针为 thorner03 硬编码，却指向 thanson03b。`nested_error=2 (missing_mod)` 这个错误码把
   "地图不对"伪装成了"依赖缺失"，而我顺着错误码的字面意思走了很久。
   **下次遇到 missing_mod，先核对探针目标与地图身份，再动依赖。**

2. **一个被藏起来的测试比一个红的测试更危险。** `collect_ignore_glob` 让整个项目套件在此后每一轮
   都诚实地报 "32 passed"——诚实地报了一个不完整的数。上一轮的总结里我甚至写下了
   "Stage 09 守卫已绿"，而它压根没跑。已加元守卫 + 阳性对照堵死这条路。

3. **状态文件会比代码活得更久。** Stage 09 整个目录都是未跟踪文件，`git reset --hard` 删不掉它们，
   于是一套描述"已不存在的实现"的 result/log/self-assessment 存活了下来，还被我在后续轮次里当成事实引用。
   凡是 untracked 的状态文件，必须和它所描述的代码一起校验，否则就是定时误导源。

## Next action

Stage 09 收口。RO-AI-001 按"静态不可约 + 已审计"长期挂账，不作为待修项推进。
若要继续扩大原生覆盖，下一步是把同一探针泛化到其余地图（需要为每张图提取各自的
gate unit / region / rescue 调用，而不是复用 thorner03 的硬编码常量）。
