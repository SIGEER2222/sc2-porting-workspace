# 斗蛐蛐 Runtime VM

斗蛐蛐插件的开发入口是实时 `function.invoke`，不是静态 Catalog/Event 注入。启动时只把 Vibe kernel 和 `LibDouQuquRuntime.galaxy` 挂到本次 staged copy；单位和效果只有收到 runtime 调用后才会在当前 SC2 会话中发生。

## 验收范围

`/api/vibe/invoke`、`/api/vibe/run-vm` 和 `dou_ququ_runtime_probe.py` 验证的是显式 VM API：调用方直接请求 `douququ.*`，随后观测对应副作用。它们不能证明普通游戏内攻击、死亡、击杀或时间流逝会自动触发规则。

自动行为只能在同一证据窗口同时具备以下因果链时标为通过：真实游戏事件、运行时事件源向 VM 的带关联 ID 记录、以及原始观察中可见的预期结果。没有这三段证据时，行为状态必须是 `NOT_EXERCISED` 或 `BLOCKED`，不得使用泛化的 `PASS`。

## 启动

使用批准的 WebUI/launcher 入口：

```powershell
.\tools\cmre-webui\start-dou-ququ-runtime.ps1 `
  -Map "<斗蛐蛐原图或解包目录>" `
  -WebPort 8777 `
  -ApiPort 5896 `
  -AutoLaunch
```

浏览器进入 `http://127.0.0.1:8777/` 的“运行时调试”页即可连接、选择函数并查看实时观测。

## 直接调用

函数目录：

```powershell
curl.exe http://127.0.0.1:8777/api/vibe/catalog
```

单个 runtime 函数：

```powershell
$body = @{
  functionId = "douququ.unit.spawn"
  args = @{ unit_type = "Reaver"; owner = 1; x = 20.0; y = 20.0 }
} | ConvertTo-Json -Depth 10

curl.exe -X POST http://127.0.0.1:8777/api/vibe/invoke `
  -H "Content-Type: application/json" `
  --data-binary $body
```

返回中的 `record.result` 是 SC2 runtime 返回值；`record.status=passed` 只表示该函数在当前 SC2 session 返回 `error_code=OK`。

## 运行时 VM 程序

VM 入口是 `POST /api/vibe/run-vm`，程序格式为 `vibe-debug/1`：

```powershell
$program = Get-Content .\tools\cmre-webui\dou_ququ_runtime_full.json -Raw | ConvertFrom-Json
$request = @{ program = $program } | ConvertTo-Json -Depth 30
curl.exe -X POST http://127.0.0.1:8777/api/vibe/run-vm `
  -H "Content-Type: application/json" `
  --data-binary $request
```

`steps` 支持 `call`、`repeat`、`assert`；`call` 的 `save` 和 `{"$ref":"vars.name.tag"}` 可用于串联单位 tag。WebUI 的 VM 编辑器提交的也是同一个接口和 schema。

## 动态脚本（无需重启）

`POST /api/vibe/run-script` 接收一个小型文本脚本，并即时编译成同一个
`vibe-debug/1` VM program，在当前已连接的 SC2 session 执行。它不热编译任意
Galaxy 源码；它只调用已经随地图加载的、白名单注册过的 `function.invoke`。

示例：

```text
let status = RuntimeStatus();
assert status.active == true;
let marine = UnitCreate(1, "Marine", 90.0, 90.0);
step 8;
let snapshot = Snapshot();
assert snapshot.marineCount >= 1;
```

支持的语句：

- `let name = UnitCreate(owner, "UnitId", x, y);`
- `PlayerSetMinerals(owner, minerals);`
- `let s = Snapshot();` / `let status = RuntimeStatus();`
- `ReplaceScarabProjectile("UnitId");`：编译为 `vibe.catalog.set`，设置 `EffectData.ScarabLM.AmmoUnit`，只证明显式 Catalog API 路径；真实攻击换弹仍需 live 事件/观察证据。
- `call douququ.some.function {"json":"args"} as saved;`
- `step 16;`
- `assert saved.field == true;`，比较符支持 `==`、`!=`、`>=`、`<=`、`contains`。

执行边界：脚本源码本身在 WebUI/Python 侧编译为 VM 指令；每个实际游戏副作用仍由
SC2 内已编译的 Galaxy handler 完成，因此改 handler 源码仍必须重载地图。

## 动态规则（事件驱动）

`POST /api/vibe/rules` 接收规则 DSL，编译成一组事件过滤器和 `vibe-debug/1`
程序。规则保存在当前 WebUI runtime 进程内；事件泵读到新的
`GalaxyVibeEvents` 事件后，先按 `eventType` 和 `where` 条件匹配规则，再把
`$payload.*`、`$event.*`、`$correlation_id` 模板值物化为真实 JSON 参数并执行 VM。
命中动态规则的事件不会再走内置自动分发兜底。

示例：

```text
rule "vulture death adapter" on unit_died where payload.victimType == "Vulture" {
  call douququ.auto.death {"correlation_id":"$correlation_id","killer_tag":"$payload.killerTag","victim_owner":"$payload.victimOwner","victim_tag":"$payload.victimTag","victim_type":"$payload.victimType","victim_x":"$payload.victimX","victim_y":"$payload.victimY"};
}
```

规则边界：这是基于已编译基础库的事件脚本，不是 Galaxy 热编译。它能组合现有
`function.invoke` primitive、条件、变量模板和 VM steps；新增 Galaxy handler、Catalog
对象或 trigger 函数仍必须随下一次地图加载编译进地图。

管理接口：

```powershell
curl.exe -X POST http://127.0.0.1:8777/api/vibe/rules `
  -H "Content-Type: application/json" `
  --data-binary (@{ source = $rules } | ConvertTo-Json)
curl.exe -X POST http://127.0.0.1:8777/api/vibe/rules/clear -d "{}"
curl.exe http://127.0.0.1:8777/api/vibe/rules
curl.exe "http://127.0.0.1:8777/api/vibe/scripts?mapName=亡者之夜.SC2Map&mapPackage=cmre&commander=TerranAlenger3"
```

`/api/vibe/scripts` 返回当前地图、DocumentInfo 依赖包和其中 `.galaxy` 源文件的静态 registry，包含 package、path、sha256、include 列表和 dependency 状态。该 registry 用于 VM 可审计上下文；它不把源码热编译进已经运行的 SC2。



## 函数执行日志

每次真实 runtime function call 都追加到：

```text
artifacts/projects/cmre-porting/stage27-dou-ququ-behavior-plugin/runtime/douququ-runtime-vm-call-log.jsonl
```

也可通过只读接口读取最近记录：

```powershell
curl.exe "http://127.0.0.1:8777/api/vibe/call-log?limit=200"
curl.exe http://127.0.0.1:8777/api/vibe/trace
```

每条 call 记录包含 `timestamp`、`session_id`、`port`、`origin`（`api`/`vm`/`connect`）、`function_id`、`args`、`result`、`error`、状态和耗时。连接握手的 `douququ.runtime.status` 也会记录，便于区分用户调用和 VM 调用。

作者弹窗清理只作用于 `artifacts/` 下的运行副本；原始 `.SC2Map` 不会被修改，也不计入 runtime 效果验证。显式 VM 调用的 SC2 返回和 JSONL 只可作为 API 验证；自动效果必须满足上方的完整事件链。

## Galaxy Script Lab

运行时页现在有 `Galaxy Runtime Script Lab`。编辑的不是 Python VM 规则，而是实际会被
挂载进下一份斗蛐蛐 staged map 的 `LibDouQuquUser.galaxy`。默认入口是：

```galaxy
string libDouQuquUser_gf_Run(string argsJson)
```

默认源码直接调用 `UnitCreate`、`PlayerModifyPropertyInt` 和 `DataTableSet*`。
UI 的“校验源码”只做结构检查；“保存源码”写入 `artifacts/`；“暂存并打包”会复制地图、
挂载该 `.galaxy` 文件并生成新的 `.packed.SC2Map`。SC2 是静态编译运行时，不能在已经
加载的进程里热编译任意 Galaxy，因此暂存后必须重载斗蛐蛐地图，随后用
`douququ.user.run` 执行新源码。当前会话点击“执行 Galaxy”只会调用已经加载的入口，
不会伪装成热加载。

相关接口：

```text
GET  /api/vibe/galaxy-script
POST /api/vibe/galaxy-script/validate
POST /api/vibe/galaxy-script/save
POST /api/vibe/galaxy-script/stage
POST /api/vibe/invoke  {"functionId":"douququ.user.run", ...}
```
