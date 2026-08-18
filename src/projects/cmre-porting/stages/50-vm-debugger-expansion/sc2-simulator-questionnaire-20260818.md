# SC2 模拟器推进问卷

> 用途：回答这些问题后，AI 可以更准确地决定下一步是补模拟器规则、补测试场景、补 SC2 实机参考校准（可选），还是推进模拟器自身的验证链。
>
> 填写方式：每题在“回答”后写你的选择或说明；不知道可以写“不确定 / AI 建议”。

## 最优先回答的 10 个

| 优先级 | 问题编号 | 问题 | 回答 |
|---:|---:|---|---|
| 1 | 1 | 模拟器核心目标是替代 SC2 runtime 做自动化验证，还是辅助筛选/预演行为？ |  |
| 2 | 4 | 模拟器结果允许作为最终验收吗，还是只作为更高层验证前的预筛证据？ |  |
| 3 | 6 | 模拟器采用什么覆盖/成熟度分级？例如 missing / partial / implemented / calibrated。 |  |
| 4 | 8 | 一个行为什么时候可以从 implemented 升到 calibrated（已用参考样本校准）？ |  |
| 5 | 13 | 下一批最该补的是哪一族：Terran、Protoss、Zerg，还是中立/地图机制？ |  |
| 6 | 20 | Ability 系统优先补主动技能、自动施法、buff/debuff、validator、requirement，还是 effect chain？ |  |
| 7 | 25 | Golden scenarios 应该是“小而准”的单机制测试，还是“像真实地图”的综合战斗场景？ |  |
| 8 | 29 | 每次模拟是否都必须生成 deterministic hash，方便判断行为是否悄悄变化？ |  |
| 9 | 33 | 哪些行为需要可选的 SC2 实机参考样本来校准，而不是只靠模拟器内部断言？ |  |
| 10 | 39 | 模拟器代码是否允许改 reference/sc2-ally-bot，还是只能通过 CMRE project-local adapter 包装？ |  |

---

## A. 目标路线

### 1. 这个模拟器的核心目标是什么？
建议选项：
- A. 替代 SC2 runtime 做大部分自动化验证
- B. 作为 native runtime 前的预筛/预演工具
- C. 作为调试、定位、生成 evidence 的辅助工具

回答：
A

### 2. 你更关心 CMRE 地图适配，还是通用 SC2 规则模拟器？
建议选项：
- A. 优先 CMRE
- B. 优先通用 SC2 规则
- C. CMRE 先行，但设计保持可通用

回答：
B

### 3. 当前阶段优先服务哪条线？
建议选项：
- A. AI ally 行为验证
- B. 地图任务逻辑
- C. 指挥官平衡
- D. VM/debugger evidence

回答：
A

### 4. 模拟器结果允许作为最终验收吗？
建议选项：
- A. 可以，部分场景 simulator pass 即 final pass
- B. 不可以，只能作为更高层验证前置证据
- C. 视机制而定，需分级定义

回答：
C

### 5. 对外汇报时是否必须永远区分 simulator / static / runtime / blocked？
建议选项：
- A. 必须严格区分
- B. 可以合并成 pass/fail
- C. 只在关键结论里区分

回答：
A

---

## B. 保真度分级

### 6. 模拟器采用什么覆盖/成熟度分级？
建议选项：
- A. missing / partial / implemented / calibrated
- B. todo / partial / pass
- C. 自定义更细粒度等级

回答：
无意义问题

### 7. 一个行为什么时候可以从 partial 升到 implemented？
建议选项：
- A. 有 deterministic scenario + focused test
- B. 有多个场景覆盖主要边界
- C. 必须与 catalog/source 规则一致

回答：
无意义问题

### 8. 一个行为什么时候可以从 implemented 升到 calibrated？
建议选项：
- A. 必须有 SC2 实机参考样本校准
- B. simulator + static/source 规则足够
- C. 只对关键机制要求外部参考校准

回答：
无意义问题

### 9. 如果模拟器和 SC2 实际规则不一致，优先怎么处理？
建议选项：
- A. 优先改模拟器贴近 SC2 实际规则
- B. 记录 divergence，继续使用 simulator
- C. 先判断是不是参考样本/观测不完整

回答：
无意义问题

### 10. 是否接受近似但稳定的规则？
例如简化寻路、简化碰撞、简化 target acquisition。
建议选项：
- A. 接受，只要标 partial
- B. 不接受，关键规则必须追求 parity
- C. 分系统决定

回答：
C

### 11. cooldown、acceleration、turn rate、weapon backswing 等细节是否必须追求 SC2 实际规则一致性？
建议选项：
- A. 必须
- B. 暂时不必
- C. 只对战斗/平衡场景必须

回答：
A

### 12. 随机数要严格可复现，还是接近 SC2 分布即可？
建议选项：
- A. 严格 deterministic
- B. 分布接近即可
- C. 测试场景 deterministic，模拟场景可随机

回答：
C

---

## C. 规则覆盖优先级

### 13. 下一批最该补的是哪一族？
建议选项：
- A. Terran
- B. Protoss
- C. Zerg
- D. 中立/地图机制

回答：
D

### 14. Protoss 的优先缺口是什么？
建议选项：
- A. 护盾/能量
- B. 折跃/科技树
- C. 单位技能
- D. 暂不优先

回答：
A

### 15. Zerg 的优先缺口是什么？
建议选项：
- A. 幼虫/注卵
- B. 菌毯/变异
- C. Burrow
- D. 生产节奏

回答：
D

### 16. 升级系统应该先覆盖什么？
建议选项：
- A. 通用攻防
- B. 指挥官特定升级
- C. 科技需求和 unlock

回答：
C

### 17. 经济系统是否需要模拟 worker saturation / travel time / 气矿效率？
建议选项：
- A. 需要
- B. 暂时只要资源增减正确
- C. 只在平衡报告里需要

回答：
A

### 18. 建造系统是否需要严格模拟 footprint / placement blocker / power field / creep requirement？
建议选项：
- A. 需要严格模拟
- B. 只需要合法/非法大致判断
- C. 分 race/地图机制推进

回答：
C

### 19. 战斗系统优先补哪些？
建议选项：
- A. armor 类型和 bonus damage
- B. projectile / missile travel
- C. splash
- D. attack acquire / target sort

回答：


### 20. Ability 系统优先补什么？
建议选项：
- A. 主动技能
- B. 自动施法
- C. buff/debuff
- D. validator / requirement
- E. effect chain

回答：
A

### 21. Vision 系统是否要模拟高地、隐形、反隐、战争迷雾？
建议选项：
- A. 都要
- B. 先只做 target visibility
- C. 先做隐形/反隐

回答：
A

### 22. Trigger/Galaxy 子集要覆盖到什么程度？
建议选项：
- A. 事件 + 变量 + 函数调用
- B. 加上 Wait / async trigger
- C. 加上 DataTable / Bank
- D. 只要测试场景需要的最小子集

回答：
A

### 23. 是否需要支持地图任务机制？
例如 objectives、waves、boss phase、cinematic skip。
建议选项：
- A. 需要，且优先
- B. 需要，但晚点
- C. 暂时不需要

回答：
B

### 24. 指挥官机制优先覆盖哪些？
建议选项：
- A. Raynor
- B. Mengsk
- C. Alenger
- D. CMRE 自定义 commander

回答：
D

---

## D. 场景与测试

### 25. Golden scenarios 应该是什么风格？
建议选项：
- A. 小而准的单机制测试
- B. 像真实地图的综合战斗场景
- C. 两者都要，分层维护

回答：
A

### 26. 每个机制是否都需要 strict scenario 和 relaxed/smoke scenario？
建议选项：
- A. 需要
- B. 只对关键机制需要
- C. 不需要，保持简单

回答：
B

### 27. Scenario 胜负条件应该更像游戏目标还是测试断言？
建议选项：
- A. 游戏目标
- B. 测试断言
- C. 两套都支持

回答：
A

### 28. 测试失败时最需要输出什么？
建议选项：
- A. world snapshot
- B. event trace
- C. action log
- D. coverage diff
- E. divergence report

回答：
E

### 29. 每次模拟是否都必须生成 deterministic hash？
建议选项：
- A. 必须
- B. 只对 regression/golden scenario 必须
- C. 不需要

回答：
C

### 30. 是否要为每个 stage 固定 artifact schema？
建议选项：
- A. 必须固定，防止 AI 随意改报告结构
- B. 只对关键 stage 固定
- C. 暂时不固定

回答：
B

### 31. Regression 更重视数量还是可解释性？
建议选项：
- A. 数量多，覆盖广
- B. 每个 scenario 可解释、可定位
- C. 先小而准，再扩大数量

回答：
C

### 32. 是否需要 snapshot branch replay？
建议选项：
- A. 需要，用来比较不同规则实现
- B. 只在调试 divergence 时需要
- C. 暂时不需要

回答：
A

---

## E. SC2 实机参考校准（可选）

> 说明：这一节不是说“做模拟器必须依赖 native runtime”。它只用于回答：当我们声称某个模拟规则“像 SC2”时，是否需要拿真实 SC2 行为样本作为参考校准。模拟器本身仍然可以独立开发、独立测试、独立验收。

### 33. 哪些行为需要可选的 SC2 实机参考样本来校准？
建议选项：
- A. normal start
- B. unit order
- C. combat damage
- D. ability effect
- E. trigger dispatch
- F. VM trace

回答：


### 34. 如果做 SC2 实机参考校准，最小证据链是什么？
建议选项：
- A. launcher log + ScriptError verdict
- B. 再加 SC2 API frame advance
- C. 再加 Bank observation
- D. 再加 screenshot/video

回答：


### 35. 如果本机 SC2 / packing / StormLib 不可用，是否允许模拟器阶段继续推进？
建议选项：
- A. 允许
- B. 不允许，必须先修实机校准链
- C. 允许但必须单独记录 blocker

回答：
C

### 36. SC2 实机参考校准应优先验证哪些？
建议选项：
- A. normal start
- B. unit order
- C. combat damage
- D. ability effect
- E. trigger dispatch
- F. VM trace

回答：


### 37. simulator 和 SC2 参考样本的差异报告要定位到哪一级？
建议选项：
- A. scenario
- B. loop
- C. entity
- D. system/event
- E. catalog field

回答：


### 38. 是否要建立实机参考不可用时的替代验收规则？
例如 static/source rule + simulator scenario + explicit blocker。
建议选项：
- A. 需要
- B. 不需要
- C. 只对非关键机制需要

回答：


---

## F. 工程化与边界

### 39. 模拟器代码是否允许改 reference/sc2-ally-bot？
建议选项：
- A. 允许直接改 reference/sc2-ally-bot
- B. 不允许，只能通过 CMRE project-local adapter 包装
- C. 先 adapter，证明通用后再 upstream/reference

回答：
A

### 40. 未来 AI 改模拟器时，是否必须先更新 coverage matrix / result.json / issues.json，再提交代码？
建议选项：
- A. 必须
- B. 只对阶段推进必须
- C. 不需要，代码优先

回答：
B

---

## 额外备注

如果上面没有覆盖到你的偏好，可以写在这里：


