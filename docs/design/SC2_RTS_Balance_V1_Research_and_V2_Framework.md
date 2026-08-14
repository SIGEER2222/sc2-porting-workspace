# SC2 风格 RTS 单位平衡：V1 研究结论与 V2 可校准框架

> 版本：V2 research draft  
> 日期：2026-08-12  
> 目标：作为 `RTS Unit Balance Calculator v1.0` 的研究升级说明，并为 V2 计算器设计提供数学与数据结构依据。

---

## 0. 核心结论

SC2 风格 RTS 的单位平衡不能归结为“矿/气换算 + DPS/成本”。

更合理的层级是：

\[
\text{单位平衡}
=
\text{经济约束}
+
\text{单位自身价值}
+
\text{定位价值}
+
\text{空间/阵型价值}
+
\text{技能价值}
+
\text{场景边际价值}
+
\text{生产系统价值}
\]

因此，V1 的：

\[
BalanceScore=\frac{V_{static}}{C}
\]

适合做第一轮 sanity check，但 V2 应升级为：

\[
\boxed{
BalanceScore_i(S,A)
=
\frac{
V_{base,i}\cdot R_i\cdot F_i(S,A)\cdot K_i(S,A)
}{
C_i
}
}
\]

其中：

- $V_{base}$：单位自身的基础战斗价值；
- $R$：Unit Role / 定位价值；
- $F$：Formation / Collision / Terrain / Range 的空间利用率；
- $K$：技能、AOE、目标类型、微操等场景价值；
- $S$：战斗场景；
- $A$：军队组合；
- $C$：矿、气、人口、生产时间等机会成本。

最重要的设计原则是：

> **不要要求所有单位的“平均性价比”完全相等，而要让同定位单位在同类场景下可比，让不同定位单位在预期场景集合的边际价值可控。**

---

# Part I：V1 研究结论

## 1. 四维成本仍然是正确的起点

把成本表示成向量：

\[
C_i=(M_i,G_i,S_i,T_i)
\]

其中：

- $M$：Minerals
- $G$：Gas
- $S$：Supply
- $T$：Build / Warp / Morph Time

初版可以使用影子价格：

\[
C_{scalar}=P_MM+P_GG+P_SS+P_TT
\]

但是这些 $P$ 不应永久写死。它们应由经济数据、生产吞吐、人口压力和历史平衡样本校准。

推荐把四种成本分成两个概念：

### 资源机会成本

\[
C_{econ}=P_MM+P_GG
\]

### 系统约束成本

\[
C_{constraint}=P_SS+P_TT
\]

这样可以避免把人口、生产线和资源误认为同一种成本。

---

## 2. 单位价值不能只看 DPS / Cost

SC2 社区长期会同时看：

- Cost / Supply
- HP / Supply
- DPS / Supply
- HP / Cost
- DPS / Cost

这说明 “cost efficiency” 本身就是多维指标，而不是单一比值。

例如当前 SC2 数据中：

- Marine：50M、1 supply、18s，45 HP，9.8 DPS，Range 5；
- Marauder：100M/25G、2 supply、21s，125 HP，9.3 DPS，Range 6，并有对 Armored bonus 与 Concussive Shells；
- Stalker：125M/50G、2 supply、27s，160 总防御（80 HP + 80 Shield），9.7 DPS，Range 6，Speed 4.13，并可 Blink；
- Immortal：250M/100G、4 supply、39s，300 总防御，17.5 DPS，对 Armored 有 +30 bonus，并有 Barrier；
- Siege Tank：150M/125G、3 supply、32s，175 HP，Tank/Siege 两种武器形态，Siege Mode Range 13 且带 splash；
- Zealot：100M、2 supply、27s，150 总防御，18.6 DPS，近战，并有 Charge；
- Roach：75M/25G、2 supply、19s，145 HP，11.2 DPS，Range 4；
- Hydralisk：100M/50G、2 supply、24s，90 HP，20.4 DPS，Range 5；
- Colossus：300M/200G、6 supply、54s，350 总防御，18.7 DPS，Range 7，线性 AOE，并可被反空攻击；
- Zergling：25M、0G、0.5 supply、17s，35 HP，10 DPS，Speed 4.13；两个 Zergling 来自一个生产周期，且小体积、高机动、群体包围是其核心定位。

---

## 3. 生产时间是“真实成本”，而不仅仅是一个面板属性

对于固定生产建筑：

\[
Throughput_i=\frac{1}{T_i}
\]

或者从经济角度：

\[
TA_i=\frac{C_i}{T_i}
\]

更有用的指标是：

\[
ArmyValueRate_i=\frac{V_i}{T_i}
\]

因为一个单位即使单体性价比高，如果生产速度低，整体军队的单位/分钟可能仍然受限。

SC2 的 5.0.16 就是很好的现实案例：Blizzard 同时修改了经济、Supply、Gateway/Warp Gate 生产时间和具体 Gateway 单位的 cooldown / production timing。说明生产系统本身就是 balance knob，而不是单位价格的附属参数。

---

## 4. Unit Role 必须是一等公民

不要做：

\[
V_{all}=w_{HP}HP+w_{DPS}DPS+w_RRange+\cdots
\]

然后强迫所有单位都对齐 1.00。

应该先给单位一个或多个 archetype：

- Frontline / Tank
- General DPS
- Anti-Armor
- Anti-Air
- AoE
- Siege
- Mobile / Harass
- Assassin / Burst
- Control / Support
- Scout / Vision
- Economic / Production support

然后定义：

\[
V_{base}(i,r)
\]

也就是：

> 单位 $i$ 在定位 $r$ 下的价值。

例如：

- Marine 的“泛用 DPS”价值高；
- Zealot 的“前排/近战接敌”价值高；
- Marauder 的“反 Armored + Slow”价值高；
- Siege Tank 的“阵地 / AOE / 区域控制”价值高；
- Zergling 的“低 cost + 高数量 + surround”价值高。

这比让 Marine、Tank、Zergling 全部共享一套静态权重合理得多。

---

# Part II：V2 的核心升级

## 5. V2 不再使用一个固定的“单位价值”

V2 应使用：

\[
\boxed{V_i(S,A)}
\]

即单位在特定 Scenario + Army Composition 下的价值。

例如：

\[
V_{Marine}(20M\ vs\ 5Roach)
\]

与：

\[
V_{Marine}(20M\ +\ 2Medivac)
\]

是不同的。

同理：

\[
V_{Tank}(\text{open field})
\]

与：

\[
V_{Tank}(\text{choke + vision + frontline})
\]

也不同。

---

## 6. V2 的四层模型

### Layer 1 — Economic

\[
C_i=P_MM_i+P_GG_i+P_SS_i+P_TT_i
\]

### Layer 2 — Static Unit Value

\[
V_{static}=f(EHP,DPS_{ground},DPS_{air},Armor,Range,Speed,TargetBonus)
\]

### Layer 3 — Combat Scenario Value

\[
V_{combat}=f(target,formation,collision,terrain,AOE,projectile,overkill,skills)
\]

### Layer 4 — Strategic / Composition Value

\[
V_{strategic}=f(composition,production,tech,map,timing,counter\ network)
\]

最终：

\[
\boxed{V_{final}=V_{static}\cdot RoleModifier\cdot ScenarioModifier\cdot CompositionModifier}
\]

---

# Part III：碰撞体积、空间和阵型

## 7. Collision 不能作为简单 +5% / -5%

SC2 的 Unit Statistics 中明确把 Size 定义为单位的碰撞直径；这意味着碰撞体积会直接改变：

- 一条战线最多能放多少单位；
- 一支远程军队能否形成有效 concave；
- 后排单位能否输出；
- 近战单位能否包围；
- 单目标被多少单位同时 focus；
- AOE 每次命中多少目标；
- 单位移动与堵路效率。

因此 V2 应定义：

\[
N_{effective}=N\cdot FormationEfficiency
\]

以及：

\[
DPS_{army}=\sum_i DPS_i\cdot FireParticipation_i
\]

其中：

\[
0\le FireParticipation_i\le1
\]

不是所有拥有 DPS 的单位都能同时输出。

---

## 8. Collision 的推荐建模方法

不要：

\[
CollisionValue\propto 1/r^2
\]

直接作为最终分数。

可以把它作为第一版先验：

\[
PackingCapacity\propto \frac{1}{r^2}
\]

但最终使用场景模拟。

推荐使用三个指标：

### Frontline Utilization

\[
FU=\frac{\text{实际接敌单位数}}{\text{理论可部署单位数}}
\]

### Fire Utilization

\[
FI=\frac{\text{实际产生攻击的单位数}}{\text{存活且在射程内的单位数}}
\]

### Surround Efficiency

\[
SE=\frac{\text{可以有效攻击目标的包围单位数}}{\text{接战单位总数}}
\]

然后：

\[
FormationModifier=g(FU,FI,SE)
\]

---

# Part IV：AOE、Target Bonus、Projectile、Overkill

## 9. AOE 不应直接转换成“固定 DPS 加成”

对于 AOE：

\[
DPS_{AOE}=DPS_{single}\times E[N_{targets}]\times HitProbability\times DamageFalloff
\]

其中 $E[N_{targets}]$ 取决于：

- 目标体积；
- 目标数量；
- 集结密度；
- 玩家控制；
- 地形；
- AOE 半径/宽度；
- 是否容易 spread。

所以 Colossus、Siege Tank、Baneling 等单位必须用场景测试而不是简单“AOE +30”。

Siege Tank 当前 Siege Mode 每发对中心区域做 40 + 30 vs Armored 的 splash，伤害随距离下降；其价值明确依赖目标聚集程度与站位。Colossus 则使用贯穿式线性范围攻击，这意味着目标排列方式本身就是价值变量。

---

## 10. Target Bonus 应按目标分布加权

例如：

\[
DPS_{expected}=DPS_{base}+P(Armored)\cdot DPS_{bonus,Armored}
\]

所以：

> Marauder 对 Armored composition 的价值会显著高于对纯 Light composition 的价值。

这也是为什么不能只给 Marauder 一个固定的“DPS”。

---

## 11. Projectile / Overkill 也应该进 V2

理论 DPS：

\[
DPS_{theory}
\]

实际有效 DPS：

\[
DPS_{effective}=DPS_{theory}\cdot(1-OverkillRate)
\]

其中：

\[
OverkillRate=f(projectileDelay,targetHP,numberOfAttackers,focusFire,micro)
\]

SC2 社区对 hitscan / projectile / overkill 的讨论也指出，投射物在集中攻击低生命值目标时存在天然的 overkill 风险。

---

# Part V：技能价值

## 12. Skill 不应该固定 +X 分

V2 对技能定义：

\[
V_{skill}=ExpectedImpact\times UsageRate\times Reliability\times Availability\times CounterplayFactor
\]

### ExpectedImpact

一次成功释放带来了多少战斗收益？

### UsageRate

单位在真实战斗中平均多久使用一次？

### Reliability

技能是否容易被打断、躲避、误用？

### Availability

Cooldown、Energy、Charges 限制多大？

### CounterplayFactor

敌人是否能够通过走位、侦测、打断等方式降低收益？

---

## 13. 典型技能的建模方向

### Blink

主要增加：

- engagement control
- retreat
- terrain access
- focus-fire break
- chase
- micro ceiling

推荐：

\[
V_{Blink}=\Delta TTK+\Delta Survival+\Delta PositionGain
\]

在场景模拟中统计。

### Stim

推荐：

\[
V_{Stim}=p_{use}\cdot\Delta DPS-HP_{cost}
\]

再根据战斗持续时间求积分，而不是简单给 +50% DPS。

### Barrier

可用：

\[
V_{Barrier}\approx ExpectedDamagePrevented
\]

而不是把技能吸收量 1:1 当生命值。

原因是 Barrier 可以在关键时刻消除一个高伤害 spike，实际价值可能高于平均伤害数字。

### Siege Mode

它既改变：

- Range
- DPS
- AOE

又改变：

- Mobility
- vulnerability
- transformation time

所以应该作为“模式切换”的场景系统，而不是单个技能参数。

---

# Part VI：基准单位体系

## 14. 不建议只有一个 Benchmark = 100

V2 建议至少使用 5 个 archetype anchors。

| Benchmark | 归一化值 | Archetype |
|---|---:|---|
| Marine | 100 | 低成本通用远程 DPS |
| Zealot | 100 | T1 前排 / 近战 |
| Marauder | 100 | 反 Armored / Slow |
| Stalker | 100 | 高机动通用远程 |
| Siege Tank | 100 | Siege / AOE / 区域控制 |

再加入：

- Zergling = swarm / surround anchor
- Immortal = premium anti-armored anchor
- Colossus = premium AOE anchor

这样会比单一 Marine = 100 更稳定。

---

## 15. 第一批代表单位真实数据

| Unit | M | G | Supply | Time | HP+Shield | DPS | Range | Core Role |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Marine | 50 | 0 | 1 | 18 | 45 | 9.8 | 5 | General DPS |
| Zealot | 100 | 0 | 2 | 27 | 150 | 18.6 | 0.1 | Frontline |
| Marauder | 100 | 25 | 2 | 21 | 125 | 9.3 | 6 | Anti-Armor |
| Stalker | 125 | 50 | 2 | 27 | 160 | 9.7 | 6 | Mobile |
| Zergling | 25 | 0 | 0.5 | 17 | 35 | 10.0 | 0.1 | Swarm |
| Roach | 75 | 25 | 2 | 19 | 145 | 11.2 | 4 | Durable Assault |
| Hydralisk | 100 | 50 | 2 | 24 | 90 | 20.4 | 5 | Ranged DPS / AA |
| Immortal | 250 | 100 | 4 | 39 | 300 | 17.5 | 6 | Premium Anti-Armor |
| Siege Tank | 150 | 125 | 3 | 32 | 175 | 20.3 tank / 18.7 siege | 7 / 13 | Siege / AOE |
| Colossus | 300 | 200 | 6 | 54 | 350 | 18.7 | 7 | Premium AOE |

**注意：** 上表的真实游戏数据与模型系数必须严格分开。表内数字来自当前 Legacy of the Void multiplayer 数据；“100”是模型归一化值，而不是 Blizzard 官方价值。

---

# Part VII：V2 的推荐数学结构

## 16. Base Value

先把所有静态指标归一化到 benchmark：

\[
x'_k=\frac{x_k}{x_{benchmark}}
\]

然后：

\[
V_{base}=\sum_k w_k x'_k
\]

推荐第一版先用：

| Dimension | 初始权重 |
|---|---:|
| EHP | 0.15 |
| Ground DPS | 0.20 |
| Air DPS | 0.05 |
| Range | 0.08 |
| Armor / mitigation | 0.07 |
| Mobility | 0.07 |
| Target bonus | 0.10 |
| Role / specialization | 0.08 |
| Utility | 0.05 |
| Skill | 0.15 |
| **Total** | **1.00** |

这些是“校准先验”，不是 SC2 官方权重。

---

## 17. Role Modifier

推荐不要让 Role 变成任意加分。

更合理：

\[
R_i(S)=1+\alpha_r\cdot Fit(i,r,S)
\]

例如一个反重型单位面对 Armored-heavy 场景时，$Fit\to1$；面对纯 Light 场景，$Fit\to0$。

这样“定位价值”来自单位和环境的匹配，而不是人为偏袒某兵种。

---

## 18. Formation Modifier

推荐：

\[
F=f(FrontlineUtilization,FireUtilization,SurroundEfficiency,AoEExposure)
\]

第一版可简化：

\[
F=0.35FU+0.35FI+0.30SE
\]

再通过模拟数据重新拟合。

---

## 19. Skill Modifier

\[
K=1+\sum_j p_j\cdot Impact_j\cdot Reliability_j\cdot Counterplay_j
\]

不要把所有技能价值加到一个“Ability Points”栏以后就不再拆。

V2 应把技能拆成独立字段：

- cooldown
- energy
- cast time
- duration
- charges
- target requirement
- effect magnitude
- counter type

---

# Part VIII：场景库

## 20. 最少要建立 12 个标准 Scenario

### T1 Mass

- 20 Marine vs 10 Zealot
- 20 Marine vs 10 Zergling

### Anti-Armor

- 10 Marauder vs 5 Roach
- 5 Immortal vs 10 Roach

### Ranged

- 10 Stalker vs 10 Marine
- 10 Hydralisk vs 10 Marine

### AOE

- 3 Siege Tank vs 30 Marine
- 3 Colossus vs 30 Zergling

### Mixed Army

- 10 Marine + 5 Marauder + 2 Medivac
- 10 Zealot + 5 Stalker + 2 Immortal
- 15 Roach + 10 Hydralisk

### Positioning

- Open field
- Narrow choke
- Concave
- Defender high ground

这样 V2 才能回答：

> “这个单位是整体强，还是只是在某一个场景强？”

---

# Part IX：边际价值

## 21. RTS 真正重要的是 Marginal Value

不是：

\[
V(n)=nV(1)
\]

而是：

\[
MV(n)=V(n)-V(n-1)
\]

典型例子：

### Marine

前 10 个单位的边际价值可能较高，因为容易形成输出线；到 60 个后，会受到射程重叠、目标不足、AOE 暴露和阵型空间不足影响。

### Siege Tank

第一批 Tank 可能迅速提高区域控制；继续堆叠后，DPS overlap、target saturation、fire lane 和 splash risk 会让边际收益下降。

所以 V2 应输出：

\[
MV_1,MV_5,MV_{10},MV_{20},MV_{40}
\]

而不仅是一个 BalanceScore。

---

# Part X：生产与组合

## 22. Unit Balance 最终是 Composition Balance

单位应该放进：

\[
\max U(A)
\]

其中 $A$ 为军队组合。

约束：

\[
\sum_i M_i x_i\le M
\]

\[
\sum_i G_i x_i\le G
\]

\[
\sum_i S_i x_i\le S
\]

\[
\sum_i T_i x_i\le ProductionCapacity
\]

然后比较：

\[
U(A_1),U(A_2),\ldots
\]

这样才能发现：

> 某单位单独看没有超模，但和某个支援单位组合后变成必选。

这也是 Marine + Medivac、Tank + Spotter、Zealot + Immortal 等组合为什么不能只用单体 cost-efficiency 判断的原因。

---

# Part XI：V2 的输出应该长什么样

不要只输出：

> BalanceScore = 1.13

应输出：

```text
Unit: Example Heavy Ranged

Overall Score:           1.08
Target Range:            0.95–1.05
Status:                  SLIGHTLY STRONG

Economic:
  Mineral Efficiency:    1.02
  Gas Efficiency:        1.11
  Supply Efficiency:     0.97
  Production Efficiency: 1.04

Static Combat:
  EHP:                   +7%
  DPS:                   +4%
  Range:                 +8%
  Mobility:              -3%

Role:
  Anti-Armor:            +12%
  General DPS:           +1%

Formation:
  Fire Utilization:      -5%
  Frontline Utilization: +2%

Ability:
  Skill Value:           +9%
  Counterplay:           -3%

Scenario:
  vs Light mass:         0.97
  vs Armored mass:       1.18
  Open field:            1.01
  Choke:                 1.14
  High-ground defense:   1.20

Marginal Value:
  1 unit:                1.06
  5 units:               1.11
  10 units:              1.17
  20 units:              1.09
```

这样 balance designer 一眼能看出来：

> **问题到底来自哪里。**

而不是只知道“这个数字大了”。

---

# Part XII：V2 的校准方法

## 23. 不要人工拍所有权重，应该做回归

V2 的最佳流程：

### Step 1

收集当前单位数据：

\[
X_i
\]

### Step 2

收集历史平衡样本：

\[
X_i^{patch}
\]

### Step 3

收集真实战斗结果：

\[
WinRate(i,j,S)
\]

### Step 4

拟合：

\[
WinProb=\sigma(\beta_0+\beta X+\gamma Scenario+\delta Role+\eta Composition)
\]

### Step 5

让系数反推：

- 1 Mineral 的隐含价值；
- 1 Gas 的隐含价值；
- 1 Supply 的隐含价值；
- 1 sec production 的隐含价值；
- Range / Speed 的边际价值；
- Skill 的场景价值；
- Collision / Formation 的价值。

### Step 6

再把得到的系数写回 Calculator。

这比“一开始决定 Mineral=1、Gas=1.5”可靠得多。

---

# Part XIII：可接受误差区间

V2 不建议所有单位都强行：

\[
0.95\le Score\le1.05
\]

推荐按定位：

| Archetype | 正常区间 |
|---|---:|
| General T1 | 0.95–1.05 |
| General T2 | 0.93–1.07 |
| Specialist | 0.90–1.10 |
| High-tech / expensive | 0.88–1.12 |
| Extreme utility / siege | 0.85–1.15 |

真正需要报警的是：

\[
Score<0.90
\]

或：

\[
Score>1.10
\]

并且：

> **如果某个单位只有在 1 个狭窄场景里 >1.10，不应马上认为它超模；应该检查它是不是合理的 counter / specialist。**

---

# Part XIV：对 V1 的一个重要修正

上一版模型有一个概念问题：

> 不能把 Collision、Skill、Role 都简单做成 Static Value 的加法项。

V2 应区分：

### Additive

适合：

- base HP
- base DPS
- armor
- resource cost

### Multiplicative

更适合：

- role fit
- formation efficiency
- skill uptime
- target matchup
- AOE target count

即：

\[
V_{final}\neq V_{HP}+V_{DPS}+V_{Skill}+V_{Collision}
\]

而更推荐：

\[
\boxed{V_{final}=V_{base}\times R\times F\times K}
\]

因为这些因素之间存在交互。

---

# Part XV：对 SC2 的一个更重要结论

SC2 的平衡不是“单位数值平衡”，而是：

\[
\boxed{
\text{Economic Balance}
+
\text{Production Balance}
+
\text{Combat Balance}
+
\text{Counter Balance}
+
\text{Composition Balance}
+
\text{Map/Position Balance}
}
\]

Blizzard 的版本实践也能看到这种思路。

例如 5.0.16 同时改动：

- 经济资源；
- Command Center / Nexus 的 supply；
- Warpgate 转换成本；
- Gateway / Warpgate 生产时间；
- 具体单位的生产 cooldown；
- 单位技能。

这说明即使面对一个“单位问题”，正确的平衡旋钮也不一定是单位伤害或资源成本。

---

# Part XVI：V2 实施优先级

建议 Calculator 2.0 按以下顺序开发：

## V2.1 — 必做

1. Archetype / Role
2. Scenario
3. Target Type / Bonus
4. Formation Efficiency
5. AOE
6. Skill uptime
7. Marginal Value
8. Production throughput

## V2.2 — 强烈推荐

1. Collision geometry
2. Projectile delay / overkill
3. Terrain / choke
4. Vision / spotter
5. Micro difficulty
6. Counterplay

## V2.3 — 最后做

1. Build-order interaction
2. Timing attack value
3. Tech opportunity cost
4. Map-specific balance
5. Composition optimization
6. Replay / telemetry calibration

---

# Part XVII：最终 V2 总公式

推荐最后使用：

\[
\boxed{
Score_i(S,A)
=
\frac{
V_{base,i}
\cdot R_i(S)
\cdot F_i(S,A)
\cdot K_i(S,A)
\cdot P_i(A)
}{
P_MM_i+P_GG_i+P_SS_i+P_TT_i
}
}
\]

其中：

- $V_{base}$：静态战斗价值；
- $R$：定位/目标匹配；
- $F$：碰撞/阵型/地形；
- $K$：技能/AOE/微操/反制；
- $P$：生产系统、科技门槛、支援组合等战略修正。

中心基准仍为：

\[
\boxed{1.00}
\]

但必须同时查看：

\[
Score(S_1),Score(S_2),...,Score(S_n)
\]

以及：

\[
MV(n)
\]

而不是只看一个平均分。

---

# 参考资料

1. Blizzard Entertainment — StarCraft II 5.0.16 Patch Notes  
   https://news.blizzard.com/en-us/article/24259080/starcraft-ii-5-0-16-patch-notes

2. Liquipedia — Unit Statistics (Legacy of the Void)  
   https://liquipedia.net/starcraft2/Unit_Statistics_%28Legacy_of_the_Void%29

3. Liquipedia — Marine (Legacy of the Void)  
   https://liquipedia.net/starcraft2/Marine_%28Legacy_of_the_Void%29

4. Liquipedia — Marauder (Legacy of the Void)  
   https://liquipedia.net/starcraft2/Marauder_%28Legacy_of_the_Void%29

5. Liquipedia — Stalker (Legacy of the Void)  
   https://liquipedia.net/starcraft2/Stalker_%28Legacy_of_the_Void%29

6. Liquipedia — Zealot (Legacy of the Void)  
   https://liquipedia.net/starcraft2/Zealot

7. Liquipedia — Roach (Legacy of the Void)  
   https://liquipedia.net/starcraft2/Roach_%28Legacy_of_the_Void%29

8. Liquipedia — Hydralisk (Legacy of the Void)  
   https://liquipedia.net/starcraft2/Hydralisk_%28Legacy_of_the_Void%29

9. Liquipedia — Immortal (Legacy of the Void)  
   https://liquipedia.net/starcraft2/Immortal_%28Legacy_of_the_Void%29

10. Liquipedia — Siege Tank (Legacy of the Void)  
    https://liquipedia.net/starcraft2/Siege_Tank_%28Legacy_of_the_Void%29

11. Liquipedia — Colossus (Legacy of the Void)  
    https://liquipedia.net/starcraft2/Colossus_%28Legacy_of_the_Void%29

12. Liquipedia — Zergling (Legacy of the Void)  
    https://liquipedia.net/starcraft2/Zergling

13. Blizzard Forums — Cost Efficiency of Units  
    https://us.forums.blizzard.com/en/sc2/t/cost-efficiency-of-units/7382

14. Valdivia — RTS balancing research project  
    https://valdiviadev.github.io/RTS-balancing-research/

15. Sorochan & Guzdial — Generating RTS Units Using Search-Based PCG and MCTS  
    https://arxiv.org/abs/2212.03387

16. Vinyals et al. — StarCraft II: A New Challenge for Reinforcement Learning  
    https://arxiv.org/abs/1708.04782

---

## 最终建议

V1 已经足够作为“单位定价 / 面板 sanity check”。

V2 不应继续增加几十个静态权重，而应转向：

\[
\boxed{
\text{Archetype}
\rightarrow
\text{Scenario}
\rightarrow
\text{Formation}
\rightarrow
\text{Skill}
\rightarrow
\text{Marginal Value}
\rightarrow
\text{Composition}
}
\]

真正的下一步，是把这些东西做进 `RTS Unit Balance Calculator v2.0`，并让它自动运行一批标准战斗场景，而不是只给一个静态 Score。
