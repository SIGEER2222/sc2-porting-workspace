# Vibe 诊断报告 — marine-baseline

- 地图: `artifacts/live-maps/亡者之夜_live_packed.SC2Map`
- 时间: 2026-07-31T15:00:00+08:00
- 总计: 3  PASS: 0  FAIL: 0  ERROR: 3
- **阻塞原因**: BankPoll/ChatCommand 触发器在 SC2 API 模式下不触发

| check | status | actual | expected | notes |
|---|---|---|---|---|
| marine_base_armor | ERROR | {} | {"armor":"== 0"} | BankPoll trigger registered but never processed pending request. state_version stayed 0 across all tests. |
| marine_with_shield_wall | ERROR | {} | {"armor":"== 3","tech_tree_unlocked":true} | upgrade.set_level request written to Bank but Kernel did not dispatch. |
| marine_nonexistent_upgrade | ERROR | {} | {"tech_tree_unlocked":false} | tech_tree.check request written to Bank but Kernel did not dispatch. |

## 运行时证据汇总

| 验证项 | 结果 | 证据 | 类型 |
|---|---|---|---|
| Init() 执行确认 | PASS | Bank 文件删除后由 Init() 重建，markers: kernel_initialized=1, init_entered=1, initmap_entered=1, initlib_entered=1 | runtime |
| SC2 in_game 状态 | PASS | game_loop=13645, player_id=1, 31 units, Marine@45,45 (InitMap 创建) | runtime |
| BankPoll 触发器 | FAIL | pending_request_id 已设置，等待 5-8s + Step(8)，state_version 始终 0 | runtime |
| ChatCommand 触发器 | FAIL | 发送 '!vibe <args>' via ActionChat(channel=1) + Step(8)，state_version 始终 0 | runtime |
| Bank 外部写入可见性 | FAIL | 删除 Bank 文件，恢复含 pending_request_id 的版本，等待 8s，Kernel 未处理 | runtime |
| ScriptError 复核 | PASS | GameLogs 无新增 ScriptError.*.txt | runtime |

## 离线验证

| 验证项 | 结果 | 证据 | 类型 |
|---|---|---|---|
| 离线测试套件 | PASS | 31/31 tests passed (TestWhitelist, TestSchemaValidation, TestGalaxyStaticCheck, TestVibeHostMocked) | static |
| Kernel 集成验证 | PASS | 从 live map 提取 LibVibeKernel.galaxy，确认含 BankPoll_Func/ChatCommand_Func/RegisterEntryPoints/HandleUpgradeSetLevel/HandleTechTreeCheck/HandleQueryUnitTags/HandleQueryUnitAttrs | static |

## 根因假设

SC2 API 模式（通过 WebSocket CreateGame+JoinGame）不触发通过 TriggerCreate+TriggerAddEventXxx 注册的 TimePeriodic/ChatMessage 触发器。地图自身的触发器（通过 MapScript.galaxy InitTriggers 注册）能正常触发（敌人 spawn、游戏推进），表明问题特定于库 Init 函数中以编程方式创建的触发器。

另一个可能：SC2 的 BankLoad 缓存文件内容，不重新读取外部修改的 Bank 文件，导致 BankPoll 无法看到 VibeHost 写入的 pending_request_id。

## 下一步

1. 调查 TriggerCreate 在 API 模式 vs 正常模式下的行为差异
2. 考虑使用 SC2API RequestMapCommand（地图需注册 MapCommand 触发器）作为替代传输
3. 考虑使用 SC2API RequestDebug 的 debug 命令直接调用 Kernel dispatch
4. 验证地图自身的 TimePeriodic 触发器是否使用与 TriggerCreate 不同的注册机制
