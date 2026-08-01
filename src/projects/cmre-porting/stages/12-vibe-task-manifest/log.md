# Stage 12 Log: Vibe task manifest

> 开启时间：2026-07-31T21:36:00+08:00  
> 关闭时间：2026-07-31T21:53:00+08:00  
> 状态：PASS

## 1. 执行摘要

本阶段把 map_extractor.py 的静态地图提取结果升级为统一 Vibe task manifest：同一份输出现在可供 simulator smoke、SC2 stub parity、live runtime launcher/.vtest 和 evidence packaging 使用。

## 2. Static 证据

- 新增 src/projects/cmre-porting/vibe/task_manifest.py
  - 读取 extract_dead_of_night() 的 MapData
  - 生成 scenario.json、regions.json、manifest.json
  - 生成 task.simulator.json、task.sc2-stub.json、task.live.json
  - 生成 runtime-recipe.json 与 scenario.vtest
  - live task 明确标记 runtime-pending、requires_launcher=true、script_error_check_required=true
- 更新 tools/galaxy-vibe/vibe.ps1
  - 新增 manifest 子命令
  - 默认输出到 artifacts/projects/cmre-porting/stage12-vibe-task-manifest
  - 本地执行轻量 simulator smoke
- 更新 tools/galaxy-vibe/run-all-validation.ps1
  - Python py_compile 覆盖 task_manifest.py
  - 必需文件清单覆盖 task_manifest.py
- 更新 tools/galaxy-vibe/workflow_status.py
  - project_vibe lane 增加 vibe.task_manifest

## 3. Artifacts

| Artifact | Evidence | 说明 |
|---|---:|---|
| artifacts/projects/cmre-porting/stage12-vibe-task-manifest/manifest.json | static | 统一 manifest |
| artifacts/projects/cmre-porting/stage12-vibe-task-manifest/scenario.json | static | 提取后的 simulator scenario |
| artifacts/projects/cmre-porting/stage12-vibe-task-manifest/regions.json | static | 地图 region metadata |
| artifacts/projects/cmre-porting/stage12-vibe-task-manifest/task.simulator.json | static | simulator smoke task |
| artifacts/projects/cmre-porting/stage12-vibe-task-manifest/task.sc2-stub.json | static/inference-pending | SC2 stub contract |
| artifacts/projects/cmre-porting/stage12-vibe-task-manifest/task.live.json | runtime-pending | live runtime contract |
| artifacts/projects/cmre-porting/stage12-vibe-task-manifest/runtime-recipe.json | runtime-pending | assertion_runner-style runtime recipe |
| artifacts/projects/cmre-porting/stage12-vibe-task-manifest/scenario.vtest | runtime-pending | launcher/REPL .vtest |
| artifacts/projects/cmre-porting/stage12-vibe-task-manifest/simulator-smoke-result.json | simulator | 轻量 simulator smoke evidence |
| artifacts/projects/cmre-porting/stage12-vibe-task-manifest/workflow-status-direct.json | static | workflow status snapshot |

## 4. Manifest 摘要

- manifest_id: dead-of-night-vibe
- scenario: 亡者之夜
- players: 6
- spawns: 1339
- regions: 51
- mapped_units: 578
- unsupported_units: 5
- scenario_hash_sha256: f9faffb74fe2398ce8e58940005c13433cea917cee6b24f69ad1c41d849212f7

## 5. Simulator 证据

轻量 smoke 不写完整 final_snapshot.json bundle；它只证明 manifest scenario 可加载、step、断言。

| 指标 | 结果 |
|---|---:|
| task_id | dead-of-night-vibe-simulator-smoke |
| backend | simulator |
| initial_entity_count | 1339 |
| final_loop | 1 |
| ops_failed | 0 |
| assertions_passed / total | 2 / 2 |
| verdict | PASS |
| trace_hash | 08425a2f1aba62dbff75abedec63abc3262f17f5fcc55f3a241b6e46299e8828 |

## 6. Verification

| 验证 | 命令 | 结果 |
|---|---|---|
| py_compile | python -m py_compile src/projects/cmre-porting/vibe/task_manifest.py | PASS |
| direct manifest | python src/projects/cmre-porting/vibe/task_manifest.py --out-dir artifacts/projects/cmre-porting/stage12-vibe-task-manifest --manifest-id dead-of-night-vibe --run-simulator-smoke | PASS; spawns=1339; regions=51; simulator smoke PASS |
| JSON parse | PowerShell ConvertFrom-Json over all Stage 12 JSON outputs | PASS |
| unified manifest | powershell -ExecutionPolicy Bypass -File tools/galaxy-vibe/vibe.ps1 manifest -RunId stage12-manifest | PASS |
| unified validation | powershell -ExecutionPolicy Bypass -File tools/galaxy-vibe/vibe.ps1 validate -RunId stage12-validate | PASS; 52/52 checks |
| workflow status | python tools/galaxy-vibe/workflow_status.py --out artifacts/projects/cmre-porting/stage12-vibe-task-manifest/workflow-status-direct.json | PASS command; overall=warn; pass=5 warn=1 fail=0 |
| whitespace | git diff --check | PASS; CRLF warnings only |

## 7. 结论

Stage 12 PASS。项目现在有统一 task/scenario manifest，可把静态 Galaxy/map extraction 输出推送到 simulator、SC2 stub 和 live runtime contract。真机 runtime 证据仍留待 Stage 13，通过 launcher + ScriptError gate 执行。
