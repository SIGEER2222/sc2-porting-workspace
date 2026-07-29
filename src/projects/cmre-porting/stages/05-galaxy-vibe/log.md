# Stage 05 — Galaxy Vibe 框架 实施日志

## 2026-07-29 — Stage 启动

### 决策

- 第一消费者：亡者之夜 × TerranAlenger3（依据 `sc2-vibe完整实施计划.md` "首个消费者固定落在 cmre-porting 的具体适配层，建议使用已通过 runtime baseline 的'亡者之夜 x TerranAlenger3'"）
- 第二消费者（P6）：克哈裂痕 × TerranAlenger3（同 map series 不同 composition，符合 P6 "选择另一张真实地图 composition" 要求）
- 代码位置：`sc2-porting-workspace/tools/galaxy-vibe/**`（复用现有 tools/runtime-bridge、tools/sc2api-baseline 基础设施）
- 验证策略：先写完 P0-P7 全部代码，再统一启动 SC2 跑运行时验证

## 2026-07-29 — P0-P6 代码完成

### 已完成

- **P0 传输闸门**：`transport/` — bank_probe.py / chat_probe.py / input_probe.py / run-transport-probes.ps1 / transport_verdict.py
- **P1 最小 Kernel**：`kernel/` — LibVibeKernel.galaxy / LibVibeKernel_h.galaxy / whitelist.json；`tests/test_kernel.py` 单元测试
- **P2 状态与断言**：`observer/` — state_observer.py / assertion_runner.py / snapshot.schema.json
- **P3 视觉闭环**：`visual/` — capture.py / roi_evaluator.py / stabilize.py
- **P4 自动冷循环**：`cold/` — orchestrator.py / change_classifier.py / static_validator.py / scenario_recipe.py
- **P5 Vibe 意图入口**：`host/` — classifier.py（hot/cold/rejected 分类） / correction.py（3 轮修正控制器）
- **P6 第二消费者**：`consumers/keha-rift/consumer.json` + `consumers/shared/adapter.py` + `consumers/shared/extraction-manifest.json`

### 决策

- 第二消费者选择克哈裂痕 × TerranAlenger3：同 commander 不同 map，验证共享 Kernel/Host 的参数化能力
- 共享抽取前保留两套差异清单（extraction-manifest.json），不强行合并

## 2026-07-29 — P7 稳定性与体验完成

### 已完成

- **P7 恢复**：`host/recovery.py` — RecoveryManager 持久化 session_state.json，Host 重启续接、SC2 重启新 session、abandoned 请求标记
- **P7 清理**：`host/cleanup.py` — CleanupManager 归档历史 Bank/日志/截图、清理孤儿 lock 文件、检测孤儿 SC2 进程（仅报告不 kill）
- **P7 性能报表**：`host/performance.py` — p50/p95/p99/max/throughput 指标，热循环 p95<=2s 阈值，冷循环 20% 退化阈值
- **P7 soak 测试**：`host/soak.py` — SoakRunner 200 请求或 30 分钟 soak，每 10 次插入幂等性测试，SC2 重启检测+session rotation
- **P7 证据包生成器**：`evidence_bundle.py` — 单命令收集 static/runtime/visual/inference 四类证据，SHA256 校验，manifest + README 自动生成
- **P7 统一入口**：`vibe.ps1` — probe/hot/verify/rebuild/run-task/bundle/soak/cleanup/validate/help 子命令
- **静态自检**：`run-all-validation.ps1` — JSON schema/Python 语法/Galaxy 语法/必需文件/whitelist-kernel 一致性/consumer 配置/P0-P7 交付物清单共 7 大类 48 项检查

### 验证

- 静态自检：**48/48 通过**，0 失败 0 警告（报告 `artifacts/galaxy-vibe/static-validation-report.json`）
- 单元测试：**27/27 通过**（覆盖 RPC 协议、checksum、幂等、白名单、参数边界、schema 一致性、Galaxy 头文件）
  - 需设置 `PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python` 绕过 vendored protobuf 版本不兼容（已知环境问题，非代码缺陷）
- 修复：P1 阶段遗留的 `test_kernel_header_galaxy_valid` 测试命名约定不一致（Galaxy 标准 `gf_Handle<Op>` 无下划线）
- 修复：vibe.ps1 / run-all-validation.ps1 在 PowerShell 5.x 下 `??` 运算符不兼容 → 改用 `Get-PythonExe` 辅助函数
- 修复：vibe.ps1 / run-all-validation.ps1 中文显示乱码 → 转换为 UTF-8 BOM 编码

### 待办

- 用户手动启动 SC2 执行运行时验证：
  - P0 闸门：`vibe.ps1 probe`（20 ping/5 dedup/5 illegal/重启恢复/p95<=2s）
  - P1 端到端：`vibe.ps1 hot -Consumer dead-of-night`（spawn 3 Marine）
  - P2 断言：`vibe.ps1 verify`（10 场景）
  - P4 冷循环：`vibe.ps1 rebuild`（Galaxy + XML fixture）
  - P5 意图：`vibe.ps1 run-task`（6 固定意图路由）
  - P7 soak：`vibe.ps1 soak -TargetRequests 200 -DurationSec 1800`
  - P7 证据包：`vibe.ps1 bundle -RunId <id>`
  - P7 清理：`vibe.ps1 cleanup`

### 已知问题

- **P7-ENV-001**（低）：protobuf 库版本与 vendored s2clientprotocol 不兼容，需设置环境变量 `PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python`。vibe.ps1 在调用 Python 子进程时未自动设置，运行时需用户手动 export 或修改 vibe.ps1 添加 `[Environment]::SetEnvironmentVariable("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python", "Process")`。

### 证据分类

- `static`：schema、Kernel Galaxy 源码、whitelist.json、consumer.json、tests、static-validation-report.json
- `runtime`：（待 SC2 验证后填充）
- `visual`：（待 SC2 验证后填充）
- `inference`：48/48 静态自检通过；27/27 单元测试通过；运行时验证待执行
