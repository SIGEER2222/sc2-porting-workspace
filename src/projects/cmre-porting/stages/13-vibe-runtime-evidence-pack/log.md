# Stage 13 Log: Vibe runtime evidence pack

> 开启时间：2026-07-31T22:24:46+08:00  
> 关闭时间：2026-07-31T23:27:01+08:00  
> 状态：PASS

## 1. 执行摘要

Stage 13 已把 Stage 12 的 live runtime contract 从 runtime-pending 推进到真实 SC2 runtime evidence。最终验证通过合规 launcher 启动 SC2，使用 packed ASCII-path 地图执行 CreateGame/JoinGame，运行 runtime-stabilized .vtest，取得 2/2 assertions PASS，并复核同一 launch window 无新增 ScriptError。

## 2. Runtime 证据

| 证据 | 结果 | Artifact |
|---|---:|---|
| Approved launcher | exit 0 | artifacts/projects/cmre-porting/stage13-vibe-runtime-evidence-pack/launcher-exit.json |
| SC2 API ready | API port 5001 OPEN | artifacts/projects/cmre-porting/stage13-vibe-runtime-evidence-pack/launcher-stdout.txt |
| CreateGame / JoinGame | OK / OK | artifacts/projects/cmre-porting/stage13-vibe-runtime-evidence-pack/launcher-stdout.txt |
| Frame advance | Advancing 15.0s | artifacts/projects/cmre-porting/stage13-vibe-runtime-evidence-pack/launcher-stdout.txt |
| Runtime assertions | 2 / 2 PASS | artifacts/projects/cmre-porting/stage13-vibe-runtime-evidence-pack/assert-results.json |
| ScriptError gate | 0 new errors | artifacts/projects/cmre-porting/stage13-vibe-runtime-evidence-pack/script-error-verdict.json |
| Combined verdict | PASS | artifacts/projects/cmre-porting/stage13-vibe-runtime-evidence-pack/vibe-verdict.json |
| Evidence bundle | PASS, 13 sha256 items | artifacts/projects/cmre-porting/stage13-vibe-runtime-evidence-pack/evidence-bundle.json |

## 3. Key fixes

- Packed map staging: SC2 API rejected the unpacked directory .SC2Map; harness now stages source map into ASCII path and packs DeadOfNight.packed.SC2Map via StormLib.
- Runtime join: galaxy_repl.py now performs CreateGame + JoinGame on the API websocket before assertions.
- Map command proto: REPL uses RequestMapCommand(trigger_cmd=...) for local protocol compatibility.
- False PASS guard: Stage harness requires launcher exit 0, current assert-results exists, total > 0, and all assertions pass.
- Frame advance: non-realtime CreateGame now advances frames during join_wait, so the game no longer appears frozen.
- Assertion stability: runtime-scenario pre-cleans baseline marines before exact-count smoke.
- Encoding/time: .vtest and launch marker reads tolerate UTF-8 BOM; launcher/harness now use UTC Unix epoch.

## 4. Verification commands

| 验证 | 命令 | 结果 |
|---|---|---|
| Runtime harness | powershell -NoProfile -ExecutionPolicy Bypass -File src/projects/cmre-porting/stages/13-vibe-runtime-evidence-pack/run-stage13-runtime-evidence.ps1 -RunId stage13-runtime -Port 5001 | PASS |
| ScriptError recheck | python tools/galaxy-vibe/script_error_check.py --since 1785511198.526352 --out artifacts/galaxy-vibe/script-error-verdict.json | PASS; count=0 |
| Combined verdict | python tools/galaxy-vibe/summarize_verdict.py | PASS |
| Python compile | python -m py_compile tools/galaxy-vibe/galaxy_repl.py tools/galaxy-vibe/script_error_check.py tools/mpq/scripts/pack_stormlib.py | PASS |
| PowerShell parse | Parser.ParseFile over stage harness and launcher | PASS |

## 5. Artifacts

- runtime-summary.json: canonical Stage 13 status summary.
- evidence-bundle.json: artifact manifest with SHA256 hashes.
- runtime-scenario.vtest: Stage 12 scenario with Stage 13 live-map baseline normalization.
- runtime-map/DeadOfNight.packed.SC2Map: packed ASCII-path map consumed by SC2 API.
- launcher-stdout.txt / launcher-stderr.txt / launcher-exit.json: compliant launcher evidence.
- assert-results.json / script-error-verdict.json / vibe-verdict.json: runtime verdict chain.

## 6. Follow-ups

- Stage 14 should focus on the project’s core vibe workflow: simulator, Galaxy parser, skill surfaces, and runtime vibe launcher as one operator loop.
- Add automatic SC2 API port fallback/retry; 5000 was flaky once, 5001 produced the final PASS.
- Keep AI ally × Dead of Night plan as a downstream application milestone after the workflow itself is stable.
