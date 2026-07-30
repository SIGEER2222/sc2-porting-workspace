# Stage 05 — Galaxy Vibe 框架（P0-P7 全量）

> 依据：`docs/sc2-vibe完整实施计划.md`、`docs/galaxy-runtime/plan.md`、`docs/galaxy-runtime/feasibility.md`、`docs/galaxy-runtime/nova-vm-deepdive.md`
> 第一消费者：亡者之夜 × TerranAlenger3（已通过 runtime baseline）
> 第二消费者（P6）：克哈裂痕 × TerranAlenger3

## 写入范围（writeScope）

仅允许新增/修改以下路径：

- `tools/galaxy-vibe/**` — Vibe 框架主体（host/kernel/transport/observer/visual/cold/evaluator/tests）
- `artifacts/galaxy-vibe/**` — 阶段证据产物
- `src/projects/cmre-porting/stages/05-galaxy-vibe/**` — 本 stage 的 plan/log/result/issues
- `src/projects/cmre-porting/project.json` — 项目配置（仅本 stage 相关字段）
- `tools/launchers/launch-galaxy-vibe.ps1` — 新增批准 launcher（不修改已有 launcher）

禁止修改：
- 已注册只读源（reference/**、外部仓库）
- 自动生成的 `MapScript.galaxy` / `LibHASH*.galaxy`
- 已有的 `launch-cmre-alenger.ps1`（仅引用，不改）
- 已有 stage 目录（00-04）

## 阶段交付物

| 阶段 | 交付物 | 验证 |
|------|--------|------|
| P0 | RPC schema、PoC Kernel Galaxy、Vibe Host、三种 transport probe、`transport-verdict.json` | 20 ping/5 dedup/5 illegal/重启恢复/p95<=2s/无 ScriptError |
| P1 | 完整 Kernel 白名单注册表、参数解析、幂等缓存、错误码、单元测试 | Galaxy 编译/schema 测试/spawn 3 Marine 端到端/未知操作拒绝 |
| P2 | State Observer、snapshot schema、recipe/assertion runner、10 场景 | exists/count/equals/range/eventually/not_exists 正负样例 |
| P3 | 窗口捕获、固定镜头/分辨率/稳定帧、ROI evaluator | before/after/reset/failed PNG + 差异图 + 单位数一致 |
| P4 | 变更分类器、静态校验、staging/sync、launcher 编排、场景重建 | Galaxy fixture + XML fixture 走完整冷循环 |
| P5 | task.json、hot/cold classifier、3 轮修正控制器 | 6 固定意图路由正确 |
| P6 | 第二消费者 adapter/recipe、共享 Kernel/Host 抽取 | 第二消费者通过 P0-P5 + 抽取后回归 |
| P7 | 恢复/清理/性能报表、`vibe.ps1` 统一入口 | 30min/200 请求 soak + 单命令证据包 |

## 统一入口

`tools/galaxy-vibe/vibe.ps1 probe|hot|verify|rebuild|run-task`

- `probe` — P0 传输闸门验证
- `hot` — P1-P3 热循环执行
- `verify` — P2 断言运行
- `rebuild` — P4 冷循环重建
- `run-task` — P5 意图入口

## 验证策略

本次实施采用"先写完全部代码再统一验证"策略：
1. 代码完成后静态自检（schema 校验、Python 语法、Galaxy 语法 lint）
2. 提供统一验证脚本 `tools/galaxy-vibe/run-all-validation.ps1`
3. 由用户启动 SC2 跑运行时验证（P0 闸门、P1 端到端、P3 视觉、P4 冷循环、P7 soak）

## 证据分类

每个技术结论必须分类为：
- `static` — 文档依赖、Catalog 定义、Galaxy 分析、源文件
- `runtime` — SC2 事件、Bank、日志、进程状态、截图、action 结果
- `inference` — 待验证假设
